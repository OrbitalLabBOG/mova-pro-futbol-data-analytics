"""No paid calls: exercise the actual JSON-RPC driver with a deterministic child."""
import json
import os
import subprocess
import pytest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def run_fake(tmp_path, tokens):
    fake=tmp_path/'fake-codex'
    fake.write_text('''#!/usr/bin/env python3
import json,sys
for line in sys.stdin:
 r=json.loads(line); method=r.get('method'); ident=r.get('id')
 if ident is None: continue
 if method=='thread/start': result={'thread':{'id':'thread-test'}}
 elif method=='turn/start': result={'turn':{'id':'turn-test'}}
 else: result={}
 print(json.dumps({'id':ident,'result':result}),flush=True)
 if method=='turn/start':
  print(json.dumps({'method':'thread/tokenUsage/updated','params':{'threadId':'thread-test','turnId':'turn-test','tokenUsage':{'total':{'inputTokens':TOKENS,'outputTokens':10,'cachedInputTokens':20}}}}),flush=True)
  if TOKENS < 100:
   print(json.dumps({'method':'item/completed','params':{'item':{'type':'agentMessage','phase':'final_answer','text':'{"ok":true}'}}}),flush=True)
   print(json.dumps({'method':'turn/completed','params':{'turn':{'id':'turn-test','status':'completed'}}}),flush=True)
 if method=='turn/interrupt':
  print(json.dumps({'method':'turn/completed','params':{'turn':{'id':'turn-test','status':'interrupted'}}}),flush=True)
'''.replace('TOKENS',str(tokens)))
    fake.chmod(0o755)
    script='''import {runMeteredTurn} from './deploy/research/codex-app-server.mjs';
const events=[];const result=await runMeteredTurn({command:process.env.MOVA_FAKE_CODEX,
 cwd:process.env.MOVA_TEST_CWD,prompt:'test',model:'mock',effort:'low',schema:{type:'object'},tokenLimit:100,
 timeoutMs:2000,onEvent:e=>events.push(e)});
process.stdout.write(JSON.stringify({result,events}));'''
    result=subprocess.run(['node','--input-type=module','-e',script],cwd=ROOT,
        env={**os.environ,'MOVA_FAKE_CODEX':str(fake),'MOVA_TEST_CWD':str(tmp_path)},capture_output=True,text=True,check=True,timeout=10)
    return json.loads(result.stdout)


def test_metered_driver_keeps_exact_usage_on_completion(tmp_path):
    result=run_fake(tmp_path,40)['result']
    assert result['status']==0
    assert result['usage']['input_tokens']==40
    assert result['usage']['output_tokens']==10
    assert json.loads(result['text'])=={'ok':True}


def test_metered_driver_interrupts_and_does_not_claim_partial_usage_is_final(tmp_path):
    data=run_fake(tmp_path,120)
    assert data['result']['status']==1
    assert data['result']['error_code']=='logical_token_guard'
    assert data['result']['usage']['input_tokens'] is None
    assert data['result']['observed_usage']['input_tokens']==120
    assert any(e.get('type')=='meter.stop' for e in data['events'])


def test_missing_executable_fails_promptly_without_hanging_rpc(tmp_path):
    script="""import {runMeteredTurn} from './deploy/research/codex-app-server.mjs';
const result=await runMeteredTurn({command:'/nonexistent/mova-codex',cwd:process.env.MOVA_TEST_CWD,
 timeoutMs:1000});process.stdout.write(JSON.stringify(result));"""
    r=subprocess.run(['node','--input-type=module','-e',script],cwd=ROOT,
        env={**os.environ,'MOVA_TEST_CWD':str(tmp_path)},capture_output=True,text=True,check=True,timeout=5)
    assert json.loads(r.stdout)['error_code']=='app_server_spawn_failed'


@pytest.mark.parametrize("extra", [False, True])
def test_invalid_tool_surface_never_dispatches_inference(tmp_path, extra):
    fake=tmp_path/'fake-codex'
    fake.write_text('''#!/usr/bin/env python3
import json,sys
for line in sys.stdin:
 r=json.loads(line)
 if 'id' not in r: continue
 method=r['method']
 if method=='turn/start': raise RuntimeError('must not dispatch')
 result={'thread':{'id':'t'}} if method=='thread/start' else INVENTORY
 print(json.dumps({'id':r['id'],'result':result}),flush=True)
'''.replace('INVENTORY',repr({'data':[{'name':'mova_evidence','tools':{'search_research_web':{}}},{'name':'unexpected_app','tools':{'send':{}}}]} if extra else {'data':[]})))
    fake.chmod(0o755)
    script="""import {runMeteredTurn} from './deploy/research/codex-app-server.mjs';
const result=await runMeteredTurn({command:process.env.MOVA_FAKE_CODEX,cwd:process.env.MOVA_TEST_CWD,
 requiredTools:['search_research_web'],timeoutMs:1000});process.stdout.write(JSON.stringify(result));"""
    r=subprocess.run(['node','--input-type=module','-e',script],cwd=ROOT,
        env={**os.environ,'MOVA_FAKE_CODEX':str(fake),'MOVA_TEST_CWD':str(tmp_path)},capture_output=True,text=True,check=True,timeout=5)
    result=json.loads(r.stdout)
    assert result['error_code']==('unexpected_tools_available' if extra else 'required_tools_unavailable')
    assert result['usage']=={'input_tokens':0,'output_tokens':0}
