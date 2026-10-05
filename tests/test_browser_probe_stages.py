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


@pytest.mark.parametrize('stage',['page_gate','sheet_state','sheet_closed','open_sheet','close_sheet','navigate'])
def test_dom_only_stages_return_direct_values_without_promise_or_network(stage):
    import shutil
    node=shutil.which('node')
    if not node:pytest.skip('Node required for DOM stage contract')
    source=(ROOT/'deploy/browser/pick-team-dom-probe.js').read_text()
    script=(source.replace('__MOVA_TEAM_ID__','1').replace('__MOVA_PROBE_STAGE__',json.dumps(stage))
            .replace('__MOVA_PROBE_EXPECTED__',json.dumps({'index':0,'element':1,'web_name':'Player 1'})))
    harness=r'''
const fs=require('fs'),vm=require('vm');const p=JSON.parse(fs.readFileSync(0,'utf8'));
const visible=()=>[{}];
const players=Array.from({length:15},(_,i)=>({innerText:`Player ${i+1}`,getClientRects:visible,click:()=>{}}));
const dismiss={getClientRects:visible,getAttribute:()=>"Dismiss",click:()=>{}};
const checks=['Captain','Vice Captain'].map((name,i)=>({checked:i===0,labels:[{innerText:name}],
    getClientRects:p.stage==='sheet_closed'?()=>[]:visible,closest:()=>document}));
const document={readyState:'complete',querySelectorAll:s=>s.includes('data-pitch-element')?players:
    s.includes('checkbox')?checks:s==='button'?[dismiss]:[]};
const result=vm.runInNewContext(p.script,{document,location:{origin:'https://fantasy.premierleague.com',pathname:'/en/my-team'}});
process.stdout.write(JSON.stringify({promise:typeof result?.then==='function',object:typeof result==='object'}));
'''
    result=subprocess.run([node,'-e',harness],input=json.dumps({'stage':stage,'script':script}),
                          text=True,capture_output=True,check=True)
    assert json.loads(result.stdout)=={'promise':False,'object':True}


def test_native_transport_pins_exact_fpl_target_and_sanitizes_errors():
    import shutil
    node=shutil.which('node')
    if not node:pytest.skip('Node required for transport contract')
    transport=(ROOT/'deploy/browser/pick-team-cdp-session.mjs').as_uri()
    harness=r'''
const {connect,selectTarget,safeCode,STAGES}=await import(process.argv[1]);
let calls=[];let sockets=[];
class Socket extends EventTarget {
 constructor(){super();sockets.push(this);queueMicrotask(()=>this.dispatchEvent(new Event('open')));}
 close(){this.dispatchEvent(new Event('close'));}
 send(raw){const d=JSON.parse(raw);calls.push(d);let result={};
 if(d.method==='Target.getTargets')result={targetInfos:[{type:'page',url:'https://fantasy.premierleague.com/en/my-team',targetId:'fixed'}]};
 if(d.method==='Target.attachToTarget')result={sessionId:'pinned'};
 if(d.method==='Runtime.evaluate')result={result:{value:{ready:true}}};
 queueMicrotask(()=>this.dispatchEvent(new MessageEvent('message',{data:JSON.stringify({id:d.id,result})})));
 }
}
const b=await connect(9222,{Socket,fetcher:async()=>({json:async()=>({webSocketDebuggerUrl:'ws://127.0.0.1:9222/devtools/browser/test'})})});
const result=await b.evaluate('fixed-stage',25000);
let ambiguous=false;try{selectTarget([{type:'page',url:'https://fantasy.premierleague.com',targetId:'a'},
 {type:'page',url:'https://fantasy.premierleague.com/en/my-team',targetId:'b'}]);}catch(e){ambiguous=e.message==='FPL_PROBE_TARGET_AMBIGUOUS';}
let dialog=false;
sockets[0].dispatchEvent(new MessageEvent('message',{data:JSON.stringify({method:'Page.javascriptDialogOpening'})}));
try{await b.evaluate('never-run',25000);}catch(e){dialog=e.message==='FPL_PROBE_DIALOG_BLOCKED';}
b.close();
process.stdout.write(JSON.stringify({result,ambiguous,dialog,safe:safeCode(new Error('private page text')),
 methods:calls.map(c=>c.method),pinned:calls.filter(c=>c.method==='Runtime.evaluate').every(c=>c.sessionId==='pinned'),
 noSave:!STAGES.has('save')}));
'''
    result=subprocess.run([node,'--input-type=module','-e',harness,transport],capture_output=True,text=True,check=True)
    payload=json.loads(result.stdout)
    assert payload=={'result':{'ready':True},'ambiguous':True,'dialog':True,'safe':'FPL_PROBE_CDP_FAILED',
                     'methods':['Target.getTargets','Target.attachToTarget','Page.enable','Runtime.evaluate'],
                     'pinned':True,'noSave':True}


def test_native_transport_never_exports_auth_or_closes_external_chromium():
    source=(ROOT/'deploy/browser/pick-team-cdp-session.mjs').read_text()
    for forbidden in ['Network.getCookies','Storage.','Browser.close','Page.close','Target.closeTarget',
                      'Page.handleJavaScriptDialog','Target.setAutoAttach','Debugger.']:
        assert forbidden not in source
    assert 'Math.min(25000,cap,remaining)' in source
    assert 'deadline=clock()+90000' in source
    docker=(ROOT/'deploy/docker/browser.Dockerfile').read_text()
    assert 'COPY deploy/browser/pick-team-cdp-session.mjs /opt/mova/pick-team-cdp-session.mjs' in docker


def test_native_host_clock_expiry_prevents_starting_transport():
    values=iter([0,87]);calls=[]
    b=module.NativeBrowser(1,9222,clock=lambda:next(values),popen=lambda *a,**k:calls.append(a))
    with pytest.raises(module.ProbeFailed,match='FPL_PROBE_CLOCK_EXPIRED'):b.stage('base',{})
    assert calls==[]


def test_native_host_timeout_closes_transport_and_never_respawns_for_cleanup(monkeypatch):
    import io
    class Process:
        stdin=io.StringIO();stdout=io.StringIO();closed=False
        def wait(self,timeout):self.closed=True
    process=Process();calls=[]
    def popen(*args,**kwargs):calls.append((args,kwargs));return process
    b=module.NativeBrowser(1,9222,clock=lambda:0,popen=popen)
    monkeypatch.setattr(module.select,'select',lambda *args:([],[],[]))
    with pytest.raises(module.ProbeFailed,match='FPL_PROBE_CDP_TIMEOUT'):b.stage('base',{})
    with pytest.raises(module.ProbeFailed,match='FPL_PROBE_CDP_FAILED'):b.stage('close_sheet',{})
    assert len(calls)==1 and process.closed and b.closed
    cmd=calls[0][0][0]
    assert cmd[-3:]==['/opt/mova/pick-team-cdp-session.mjs','1','9222']
    assert '86s' in cmd and calls[0][1]['stderr']==subprocess.DEVNULL


@pytest.mark.parametrize('response',[{'ok':False,'error_code':'private secret'},
                                    {'ok':True,'payload':'not an object'}])
def test_native_host_sanitizes_untrusted_transport_response(monkeypatch,response):
    import io
    class Process:
        stdin=io.StringIO();stdout=io.StringIO(json.dumps(response)+'\n')
        def wait(self,timeout):pass
    process=Process()
    b=module.NativeBrowser(1,9222,clock=lambda:0,popen=lambda *a,**k:process)
    monkeypatch.setattr(module.select,'select',lambda *args:([process.stdout],[],[]))
    with pytest.raises(module.ProbeFailed,match='^FPL_PROBE_(CDP_FAILED|RESPONSE_INVALID)$'):b.stage('base',{})
    b.close()


def test_cleanup_failure_preserves_primary_observation_error():
    b=FakeBrowser();original=b.stage
    def stage(name,expected):
        if name=='sheet_state':raise module.ProbeFailed('FPL_PROBE_CDP_TIMEOUT')
        if name=='close_sheet':raise module.ProbeFailed('FPL_PLAYER_SHEET_CLOSE_MISSING_OR_AMBIGUOUS')
        return original(name,expected)
    b.stage=stage
    with pytest.raises(module.ProbeFailed,match='^FPL_PROBE_CDP_TIMEOUT$'):
        module.starter_sheet(b,{'index':0,'element':1,'web_name':'Player 1'})
