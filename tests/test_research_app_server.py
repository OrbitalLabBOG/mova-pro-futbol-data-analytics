"""No paid calls: exercise the actual JSON-RPC driver with a deterministic child."""
import json
import os
import subprocess
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
 prompt:'test',model:'mock',effort:'low',schema:{type:'object'},tokenLimit:100,
 timeoutMs:2000,onEvent:e=>events.push(e)});
process.stdout.write(JSON.stringify({result,events}));'''
    result=subprocess.run(['node','--input-type=module','-e',script],cwd=ROOT,
        env={**os.environ,'MOVA_FAKE_CODEX':str(fake)},capture_output=True,text=True,check=True,timeout=10)
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
