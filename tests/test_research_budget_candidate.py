"""Isolated protocol candidate; fake child only, no paid inference or cohort mutation."""
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = './deploy/research/codex-app-server.mjs'


def run_candidate(tmp_path, mode):
    fake = tmp_path / 'fake-codex'
    fake.write_text('''#!/usr/bin/env python3
import json,sys
MODE = MODE_VALUE

def emit(method, params):
 print(json.dumps({'method':method,'params':params}),flush=True)
def meter(n):
 emit('thread/tokenUsage/updated',{'threadId':'t','turnId':'v','tokenUsage':{'total':{'inputTokens':n,'outputTokens':10,'cachedInputTokens':n-10}}})
def finish():
 emit('item/completed',{'item':{'type':'agentMessage','phase':'final_answer','text':'{"partial":true}'}})
 emit('turn/completed',{'turn':{'id':'v','status':'completed'}})
for line in sys.stdin:
 r=json.loads(line)
 if 'id' not in r: continue
 method=r['method']
 result={'thread':{'id':'t'}} if method=='thread/start' else {'turn':{'id':'v'}} if method=='turn/start' else {}
 if method=='turn/steer':
  p=r['params']
  assert p['threadId']=='t' and p['expectedTurnId']=='v'
  assert 'not_checked' in p['input'][0]['text']
  result={'turnId':'wrong' if MODE=='mismatch' else 'v'}
 if method=='turn/steer' and MODE=='error':
  print(json.dumps({'id':r['id'],'error':{'code':-1}}),flush=True)
 else: print(json.dumps({'id':r['id'],'result':result}),flush=True)
 if method=='turn/start':
  meter(20 if MODE=='below' else 55)
  if MODE in ('below','race'): finish()
 if method=='turn/steer':
  if MODE=='obey':
   meter(65);meter(75);finish()
  elif MODE=='ignore': meter(95)
  elif MODE=='late_error': finish()
 if method=='turn/interrupt':
  emit('turn/completed',{'turn':{'id':'v','status':'interrupted'}})
'''.replace('MODE_VALUE', repr(mode)))
    fake.chmod(0o755)
    script = """import {runMeteredTurn} from '%s';
const events=[]; const result=await runMeteredTurn({command:process.env.FAKE_CODEX,
 cwd:process.env.TEST_CWD,prompt:'test',model:'mock',effort:'low',schema:{type:'object'},
 tokenLimit:100,closeAtFraction:0.5,timeoutMs:2000,onEvent:e=>events.push(e)});
process.stdout.write(JSON.stringify({result,events}));""" % CANDIDATE
    result = subprocess.run(['node', '--input-type=module', '-e', script], cwd=ROOT,
        env={**os.environ, 'FAKE_CODEX':str(fake), 'TEST_CWD':str(tmp_path)},
        capture_output=True, text=True, check=True, timeout=10)
    return json.loads(result.stdout)


def test_candidate_steers_once_and_preserves_exact_cached_usage(tmp_path):
    data = run_candidate(tmp_path, 'obey')
    assert data['result']['status'] == 0
    assert data['result']['usage'] == {'input_tokens':75, 'output_tokens':10, 'cached_input_tokens':65}
    assert json.loads(data['result']['text']) == {'partial':True}
    assert sum(e.get('type') == 'meter.close_requested' for e in data['events']) == 1
    assert sum(e.get('type') == 'meter.close_acknowledged' for e in data['events']) == 1


@pytest.mark.parametrize('mode,error', [('ignore','logical_token_guard'),
    ('error','budget_close_failed'), ('mismatch','budget_close_turn_mismatch')])
def test_candidate_fails_closed_and_retains_uncertain_accounting(tmp_path, mode, error):
    result = run_candidate(tmp_path, mode)['result']
    assert result['status'] == 1
    assert result['error_code'] == error
    assert result['usage'] == {'input_tokens':None, 'output_tokens':None}
    assert result['observed_usage']['input_tokens'] >= 55


@pytest.mark.parametrize('mode', ['below', 'race'])
def test_completed_turn_remains_successful(tmp_path, mode):
    data = run_candidate(tmp_path, mode)
    assert data['result']['status'] == 0
    if mode == 'below':
        assert not any(e.get('type') == 'meter.close_requested' for e in data['events'])
