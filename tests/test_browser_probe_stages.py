"""Bounded read-only probe stages; synthetic controls do not count as live rehearsals."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('mova_probe_stages', ROOT/'deploy/bin/browser-pick-team-probe.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class FakeBrowser:
    def __init__(self):
        self.calls=[]
        self.base={'slots':[{'position':i+1,'element':i+1,'web_name':f'Player {i+1}',
                            'player_button_index':i,'switch_button_index':i,'label_matches':True}
                           for i in range(15)],
                   'signature':[[i+1,i+1,i==0,i==1] for i in range(15)],
                   'checks':dict.fromkeys(('signed_in','fifteen_api_picks','fifteen_player_controls',
                                         'fifteen_switch_controls','positional_order_matches'),True)}
        self.mutate_starter=None
        self.unchanged=True
        self.deadline=90
        self.clock=lambda:0
    def stage(self,name,expected):
        self.calls.append((name,expected))
        if name=='base':return copy.deepcopy(self.base)
        if name=='verify':return {'unchanged':self.unchanged}
        if name=='open_sheet':return {'opened':True}
        if name=='close_sheet':return {'close_requested':True}
        if name=='sheet_closed':return {'closed':True}
        i=expected['index']
        row={'available':True,'position':i+1,'element':i+1,'player_button_index':i,
             'captain_checkbox':True,'vice_captain_checkbox':True,
             'captain_checked':i==0,'vice_captain_checked':i==1}
        if self.mutate_starter:self.mutate_starter(row)
        return row

def test_all_eleven_sheets_require_independent_stages_and_fresh_final_private_state():
    browser=FakeBrowser();result=module.probe(browser,3609854)
    assert [name for name,_ in browser.calls]==['base',*(['open_sheet','sheet_state','close_sheet','sheet_closed']*11),'verify']
    assert result['status']=='pass'
    assert result['contract_version']=='fpl-pick-team-a11y-2026.10.1'
    assert all(result['checks'].values())
    assert all(result['captain_controls']['checks'].values())
    assert len(result['captain_controls']['starters'])==11
    assert 'signature' not in result

@pytest.mark.parametrize('case',['false_check','extra_check','duplicate_slot','wrong_signature','non_bool_signature'])
def test_invalid_base_never_opens_a_starter(case):
    b=FakeBrowser()
    if case=='false_check':b.base['checks']['signed_in']=False
    if case=='extra_check':b.base['checks']['invented']=True
    if case=='duplicate_slot':b.base['slots'][1]['element']=1
    if case=='wrong_signature':b.base['signature'][0][0]=999
    if case=='non_bool_signature':b.base['signature'][0][2]='true'
    with pytest.raises(module.ProbeFailed):module.probe(b,3609854)
    assert len(b.calls)==1

@pytest.mark.parametrize('key,value',[('element',999),('captain_checked','false'),('position',2)])
def test_invalid_sheet_response_cannot_be_certified(key,value):
    b=FakeBrowser();b.mutate_starter=lambda row:row.update({key:value})
    with pytest.raises(module.ProbeFailed,match='FPL_STARTER_RESPONSE_INVALID'):module.probe(b,3609854)

def test_changed_team_during_probe_rejects_result():
    b=FakeBrowser();b.unchanged=False
    with pytest.raises(module.ProbeFailed,match='FPL_TEAM_CHANGED_DURING_PROBE'):module.probe(b,3609854)

def test_wrong_captain_state_fails_complete_checks():
    b=FakeBrowser();b.mutate_starter=lambda row:row.update(captain_checked=False)
    result=module.probe(b,3609854)
    assert result['status']=='fail'
    assert result['captain_controls']['checks']['one_captain'] is False

def test_clock_expiry_prevents_another_docker_call():
    values=iter([0,87]);calls=[]
    b=module.Browser(3609854,9222,clock=lambda:next(values),run=lambda *a,**k:calls.append(a))
    with pytest.raises(module.ProbeFailed,match='FPL_PROBE_CLOCK_EXPIRED'):b.stage('base',{})
    assert calls==[]

def test_call_is_bounded_inside_container_and_outside_and_uses_stdin():
    calls=[]
    def run(cmd,**kwargs):
        calls.append((cmd,kwargs));return subprocess.CompletedProcess(cmd,0,stdout='{"unchanged":true}',stderr='')
    b=module.Browser(3609854,9222,clock=lambda:0,run=run)
    assert b.stage('verify',{})=={'unchanged':True}
    cmd,kwargs=calls[0]
    assert cmd[cmd.index('timeout')+1:cmd.index('agent-browser')]==['--signal=TERM','--kill-after=3s','25s']
    assert kwargs['timeout']==29
    assert cmd[-2:]==['eval','--stdin']
    assert '__MOVA_' not in kwargs['input']

def test_cdp_error_does_not_publish_browser_text_or_private_payload():
    def run(cmd,**kwargs):raise subprocess.CalledProcessError(1,cmd,stderr='private page text password-like value')
    b=module.Browser(3609854,9222,clock=lambda:0,run=run)
    with pytest.raises(module.ProbeFailed,match='^FPL_PROBE_CDP_FAILED$'):b.stage('base',{})

def test_staged_js_has_no_account_write_or_checkbox_toggle():
    source=(ROOT/'deploy/browser/pick-team-dom-probe.js').read_text()
    assert '5000' in source and 'AbortSignal.timeout(12000)' in source
    host=(ROOT/'deploy/bin/browser-pick-team-probe.py').read_text()
    assert 'browser.clock()+10' in host and 'browser.clock()+5' in host
    assert '.checked =' not in source and 'method: "POST"' not in source
    assert 'Save Team' not in source and 'Confirm My Choices' not in source
    assert 'finally' in host and 'FPL_TEAM_CHANGED_DURING_PROBE' in source

def test_sqlite_builder_base_is_bound_to_observed_digest():
    source=(ROOT/'deploy/docker/engine.Dockerfile').read_text()
    assert 'debian:bookworm-slim@sha256:3783cc01769c7b2b1b83a5c5ad96c815348e28ed7da68e2e3687004faa906251 AS sqlite-builder' in source

def test_navigation_context_loss_is_reconciled_with_a_fresh_page_gate():
    calls=[]
    def run(cmd,**kwargs):
        calls.append((cmd,kwargs))
        if len(calls)==1:
            raise subprocess.CalledProcessError(1,cmd,stderr='Inspected target navigated or closed')
        return subprocess.CompletedProcess(cmd,0,stdout='{"ready":true}',stderr='')
    b=module.Browser(3609854,9222,clock=lambda:0,run=run)
    b.navigate()
    assert len(calls)==2
    assert 'const stage = "page_gate"' in calls[1][1]['input']
    assert 'length === 15' in calls[1][1]['input']

def test_cold_page_polling_keeps_clock_and_leaves_probe_reserve():
    now=[0];calls=[]
    def run(cmd,**kwargs):
        calls.append(kwargs['input'])
        return subprocess.CompletedProcess(cmd,0,stdout='{"ready":false}',stderr='')
    b=module.Browser(3609854,9222,clock=lambda:now[0],run=run,sleep=lambda n:now.__setitem__(0,now[0]+n))
    with pytest.raises(module.ProbeFailed,match='FPL_PROBE_PAGE_READINESS_TIMEOUT'):b.navigate()
    assert now[0]==50 and b.deadline==90
    assert b.last_stage=='page_gate'
    assert len(calls)==51

def test_navigation_unknown_failure_is_not_ignored_or_retried():
    calls=[]
    def run(cmd,**kwargs):
        calls.append(cmd);raise subprocess.CalledProcessError(1,cmd,stderr='unknown failure')
    b=module.Browser(3609854,9222,clock=lambda:0,run=run)
    with pytest.raises(module.ProbeFailed,match='FPL_PROBE_CDP_FAILED'):b.navigate()
    assert len(calls)==1

def test_untrusted_fpl_like_error_cannot_leak_page_text():
    def run(cmd,**kwargs):raise subprocess.CalledProcessError(1,cmd,stderr='FPL_PRIVATE_SECRET_VALUE')
    b=module.Browser(3609854,9222,clock=lambda:0,run=run)
    with pytest.raises(module.ProbeFailed,match='^FPL_PROBE_CDP_FAILED$'):b.stage('base',{})


def test_chromium_starts_directly_on_read_only_team_route():
    source=(ROOT/'deploy/docker/supervisord-browser.conf').read_text()
    assert 'https://fantasy.premierleague.com/en/my-team"' in source
    assert '--user-data-dir=/var/lib/mova-fpl/browser-profile' in source


def test_sheet_read_failure_still_requests_and_verifies_local_dismissal():
    b=FakeBrowser();original=b.stage
    def stage(name,expected):
        if name=='sheet_state':
            b.calls.append((name,expected));raise module.ProbeFailed('FPL_PROBE_CDP_TIMEOUT')
        return original(name,expected)
    b.stage=stage
    with pytest.raises(module.ProbeFailed,match='FPL_PROBE_CDP_TIMEOUT'):
        module.starter_sheet(b,{'index':0,'element':1,'web_name':'Player 1'})
    assert [n for n,_ in b.calls]==['open_sheet','sheet_state','close_sheet','sheet_closed']


def test_missing_close_acknowledgement_cannot_return_a_passing_sheet():
    b=FakeBrowser();original=b.stage
    b.stage=lambda name,expected: {'close_requested':False} if name=='close_sheet' else original(name,expected)
    with pytest.raises(module.ProbeFailed,match='FPL_PLAYER_SHEET_CLOSE_MISSING_OR_AMBIGUOUS'):
        module.starter_sheet(b,{'index':0,'element':1,'web_name':'Player 1'})


@pytest.mark.parametrize('stage',['sheet_state','sheet_closed','page_gate'])
def test_one_pure_dom_read_timeout_can_be_reconciled_within_same_global_clock(stage):
    calls=[]
    def run(cmd,**kwargs):
        calls.append(cmd)
        if len(calls)==1:raise subprocess.CalledProcessError(124,cmd,stderr='CDP command timed out')
        return subprocess.CompletedProcess(cmd,0,stdout='{"available":true}',stderr='')
    b=module.Browser(1,9222,clock=lambda:0,run=run)
    assert b.stage(stage,{})=={'available':True}
    assert len(calls)==2 and b.read_timeout_reconciliations==1 and b.deadline==90
    def failed(cmd,**kwargs):raise subprocess.CalledProcessError(124,cmd,stderr='CDP command timed out')
    b.run=failed
    with pytest.raises(module.ProbeFailed) as caught:b.stage(stage,{})
    assert caught.value.stage==stage and b.read_timeout_reconciliations==1


@pytest.mark.parametrize('stage',['open_sheet','close_sheet','base','verify'])
def test_actions_and_authenticated_get_stages_are_never_repeated_after_timeout(stage):
    calls=[]
    def run(cmd,**kwargs):
        calls.append(cmd);raise subprocess.CalledProcessError(124,cmd,stderr='CDP command timed out')
    b=module.Browser(1,9222,clock=lambda:0,run=run)
    with pytest.raises(module.ProbeFailed) as caught:b.stage(stage,{})
    assert len(calls)==1 and b.read_timeout_reconciliations==0
    assert caught.value.stage==stage
