"""Real ledger/dispatcher lifecycle; browser I/O is explicitly a fixture."""
from datetime import timedelta
import json
import subprocess
from pathlib import Path

import pytest
from test_execution_attempts import _seed_authorized_service, _private_state, NOW
from mova_fpl.ops.delivery import DeliveryService, LINEUP_SCOPE


def seed(tmp_path):
    service, _, pre = _seed_authorized_service(tmp_path)
    service.db.set_control('delivery_scope', LINEUP_SCOPE, actor='test', reason='scoped delivery')
    return service, DeliveryService(service.config, service.db), pre


def test_dispatch_claim_save_verify_and_replay(tmp_path):
    service, delivery, pre = seed(tmp_path)
    assert delivery.dispatch(actor='timer', reason='due', check_only=True, now=NOW)['status'] == 'due'
    prepared = delivery.dispatch(actor='timer', reason='dispatch', now=NOW)
    assert prepared['status'] == 'prepared'
    replay = delivery.dispatch(actor='timer', reason='dispatch', now=NOW)
    assert replay['execution_id'] == prepared['execution_id']
    eid = prepared['execution_id']
    claim = service.claim(execution_id=eid, actor='timer', reason='claim', now=NOW)
    service.begin(execution_id=eid, claim_token=claim['claim_token'], pre_state=pre,
                  actor='timer', reason='begin', now=NOW+timedelta(seconds=1))
    # A parallel timer must not prepare another attempt after the apply boundary.
    assert delivery.dispatch(actor='timer', reason='parallel', now=NOW)['status'] == 'applying'
    post = _private_state(list(range(1, 11))+[12,15,11,13,14], captain=7, vice=8,
                          observed_at=NOW+timedelta(seconds=10))
    done = service.finalize(execution_id=eid, claim_token=claim['claim_token'], post_state=post,
                            actor='timer', reason='reload', now=NOW+timedelta(seconds=11))
    assert done['status'] == 'verified'
    assert delivery.dispatch(actor='timer', reason='replay', now=NOW)['status'] == 'verified'
    assert service.db.quick_check() == 'ok'


@pytest.mark.parametrize('key,value', [('kill_switch',True),('compliance_gate','pending'),
    ('browser_writes',False),('mode','shadow'),('action_level','A3'),('delivery_scope','unknown')])
def test_dispatch_never_prepares_without_exact_authority(tmp_path,key,value):
    service, delivery, _ = seed(tmp_path)
    service.db.set_control(key,value,actor='test',reason='revocation')
    assert delivery.dispatch(actor='timer',reason='dispatch',now=NOW)['status'] == 'blocked'
    assert service.db.latest_delivery_attempt('2026-27-gw03') is None


@pytest.mark.parametrize('seconds', [3*3600+1,30*60,0,-1])
def test_window_is_bounded(tmp_path,seconds):
    _, delivery, _ = seed(tmp_path)
    deadline=NOW+timedelta(minutes=90)
    assert delivery.dispatch(actor='timer',reason='window',now=deadline-timedelta(seconds=seconds))['status']=='not_due'


def test_revoked_scope_after_prepare_blocks_claim(tmp_path):
    service,delivery,_=seed(tmp_path)
    prepared=delivery.dispatch(actor='timer',reason='prepare',now=NOW)
    service.db.set_control('delivery_scope',None,actor='test',reason='revoked')
    claim=service.claim(execution_id=prepared['execution_id'],actor='timer',reason='claim',now=NOW)
    assert claim['status']=='blocked'
    assert 'DELIVERY_SCOPE_CHANGED' in claim['blocking_codes']


def test_ambiguous_save_is_never_dispatched_again(tmp_path):
    service,delivery,pre=seed(tmp_path)
    eid=delivery.dispatch(actor='timer',reason='prepare',now=NOW)['execution_id']
    claim=service.claim(execution_id=eid,actor='timer',reason='claim',now=NOW)
    service.begin(execution_id=eid,claim_token=claim['claim_token'],pre_state=pre,
                  actor='timer',reason='begin',now=NOW)
    service.fail(execution_id=eid,claim_token=claim['claim_token'],ambiguous=True,
                 actor='timer',reason='connection lost',error_code='LOST',error_detail='fixture',now=NOW)
    result=delivery.dispatch(actor='timer',reason='retry',now=NOW)
    assert result['status']=='ambiguous' and result['execution_id']==eid


def test_host_cycle_returns_before_browser_when_scope_disabled(tmp_path):
    root=Path(__file__).resolve().parents[1]
    (tmp_path/'lock').mkdir()
    cli=tmp_path/'cli'; cli.write_text('#!/bin/sh\necho \'{"status":"blocked","reason":"authority_not_enabled"}\'\n');cli.chmod(0o700)
    import os
    env={**os.environ,'MOVA_REPO_DIR':str(root),'MOVA_RUN_ROOT':str(tmp_path),
         'MOVA_BIN':str(cli),'MOVA_BROWSER_SESSION_BIN':'/usr/bin/false'}
    result=subprocess.run(['bash','deploy/bin/delivery-cycle.sh'],cwd=root,env=env,capture_output=True,text=True)
    assert result.returncode==0 and 'authority_not_enabled' in result.stdout


@pytest.mark.parametrize('field,value', [('bank',9),('made',1),('cost',4),('chip',True)])
def test_real_ledger_verifier_rejects_unexpected_finance_or_chip(tmp_path,field,value):
    service,delivery,pre=seed(tmp_path)
    eid=delivery.dispatch(actor='timer',reason='prepare',now=NOW)['execution_id']
    claim=service.claim(execution_id=eid,actor='timer',reason='claim',now=NOW)
    service.begin(execution_id=eid,claim_token=claim['claim_token'],pre_state=pre,
                  actor='timer',reason='begin',now=NOW)
    post=_private_state(list(range(1,11))+[12,15,11,13,14],captain=7,vice=8,
                        observed_at=NOW+timedelta(seconds=10))
    if field=='chip': post['chips'][0]['is_pending']=True
    else: post['transfers'][field]=value
    result=service.finalize(execution_id=eid,claim_token=claim['claim_token'],post_state=post,
                           actor='timer',reason='verify',now=NOW+timedelta(seconds=11))
    assert result['status']=='ambiguous'
    assert next(c for c in result['verification_checks'] if c['code']=='POST_FINANCE_AND_CHIPS_UNCHANGED')['passed'] is False


def test_bounded_lineup_optimizer_cannot_sell_high_value_players():
    from test_optimizer_constraints import mercado,estado,matriz
    from mova_fpl.optimizer import OptimizerConfig,solve
    from mova_fpl.rules.base import Squad,SquadPlayer
    cands=mercado()
    initial=solve(estado(cands),matriz(cands),OptimizerConfig(horizon=1))
    by_id={c.element:c for c in cands}
    squad=Squad(players=tuple(SquadPlayer(e,by_id[e].position,by_id[e].team,by_id[e].price) for e in initial.squad[1]),
                starters=initial.starters[1],captain=initial.captain[1],vice_captain=initial.starters[1][1],
                bench_order=tuple(e for e in initial.squad[1] if e not in initial.starters[1]))
    state=estado(cands,gw=2,squad=squad,ft=5,bank=10)
    xp={2:{c.element:(100 if c.element not in initial.squad[1] else 1) for c in cands}}
    result=solve(state,xp,OptimizerConfig(current_transfer_limit=0,max_hits_per_gw=0))
    assert set(result.squad[2])==set(initial.squad[1])
    assert result.buys[2]==() and result.sells[2]==() and result.hits[2]==0


def test_scoped_delivery_alerts_even_when_policy_skips_execution():
    from mova_fpl.ops.watchdog import evaluate_workflow_deadline
    workflow={'stages':[{'name':n,'status':'complete'} for n in ['observe','contextualize','research','deliberate','preflight','propose_validate']]
              +[{'name':'execute_verify','status':'skipped_policy'}]}
    report=evaluate_workflow_deadline(workflow,seconds_to_deadline=3600,delivery_required=True)
    assert report['severity']=='P1'
    assert any(r['code']=='bounded_team_delivery_not_verified' for r in report['reasons'])
    assert evaluate_workflow_deadline(workflow,seconds_to_deadline=3600,delivery_required=True,delivery_completed=True)['healthy']


def test_scheduled_host_runs_real_cli_lease_ui_plan_finalize_and_replay(tmp_path):
    """Only source refresh and browser I/O are fixtures; both host scripts and CLI are real."""
    import os,shlex,sys
    from dataclasses import replace
    from test_execution_attempts import _dom_probe_with_captain_controls
    service,_,pre=seed(tmp_path)
    root=Path(__file__).resolve().parents[1]
    run=tmp_path/'run';(run/'lock').mkdir(parents=True)
    post=_private_state(list(range(1,11))+[12,15,11,13,14],captain=7,vice=8,
                        observed_at=NOW+timedelta(seconds=10))
    for name,payload in [('pre',pre),('post',post),('probe',_dom_probe_with_captain_controls(list(range(1,16)),1,2))]:
        (tmp_path/f'{name}.json').write_text(json.dumps(payload))
    bridge=tmp_path/'bridge.py'
    bridge.write_text(f'''import sys,json
from pathlib import PosixPath
sys.path.insert(0,{str(root)!r})
from datetime import datetime,timezone
from mova_fpl.ops import cli,execution,delivery
from mova_fpl.ops.config import RuntimeConfig
class Clock(datetime):
 @classmethod
 def now(cls,tz=None):return datetime(2026,9,4,16,tzinfo=timezone.utc)
execution.datetime=delivery.datetime=Clock
config={replace(service.config,sqlite_min_version='3.0.0')!r}
cli.RuntimeConfig.from_env=lambda:config
if sys.argv[1]=='tick':
 print(json.dumps({{'status':'completed','fixture_source_refresh':True}}));sys.exit(0)
sys.exit(cli.main(sys.argv[1:]))
''')
    mova=tmp_path/'mova';mova.write_text('#!/bin/sh\nexec '+shlex.quote(sys.executable)+' '+shlex.quote(str(bridge))+' "$@"\n');mova.chmod(0o700)
    browser=tmp_path/'browser';browser.write_text(f'''#!/bin/sh
set -eu
case "$1" in
 collect)
 n=0; test ! -f {shlex.quote(str(tmp_path/'count'))} || n=$(cat {shlex.quote(str(tmp_path/'count'))})
 n=$((n+1)); echo "$n" > {shlex.quote(str(tmp_path/'count'))}
 if [ "$n" -ge 3 ]; then cat {shlex.quote(str(tmp_path/'post.json'))}; else cat {shlex.quote(str(tmp_path/'pre.json'))}; fi ;;
 probe) cat {shlex.quote(str(tmp_path/'probe.json'))} ;;
 stop) exit 0 ;;
 *) exit 2 ;;
esac
''');browser.chmod(0o700)
    driver=tmp_path/'driver.py';driver.write_text('import sys\n# Fixture browser applies once; production driver is separately exercised against DOM fixtures.\n')
    env={**os.environ,'MOVA_REPO_DIR':str(root),'MOVA_RUN_ROOT':str(run),'MOVA_BIN':str(mova),
         'MOVA_BROWSER_SESSION_BIN':str(browser),'MOVA_BROWSER_R2_DRIVER':str(driver),
         'MOVA_EXECUTE_R2_BIN':str(root/'deploy/bin/execute-r2-browser.sh')}
    # Host lease expiry uses wall clock: fixture this one clock calculation, keeping the public CLI clock fixed.
    driver_script=(root/'deploy/bin/execute-r2-browser.sh').read_text()
    driver_script=driver_script.replace('datetime.now(timezone.utc)',"datetime(2026,9,4,16,tzinfo=timezone.utc)")
    bounded_driver=tmp_path/'execute-r2';bounded_driver.write_text(driver_script);bounded_driver.chmod(0o700)
    env['MOVA_EXECUTE_R2_BIN']=str(bounded_driver)
    result=subprocess.run(['bash','deploy/bin/delivery-cycle.sh'],cwd=root,env=env,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr+result.stdout
    assert 'browser_execution_verified' in result.stdout
    assert (tmp_path/'count').read_text().strip()=='3'

    again=subprocess.run(['bash','deploy/bin/delivery-cycle.sh'],cwd=root,env=env,capture_output=True,text=True,timeout=10)
    assert again.returncode==0 and 'existing_attempt_no_duplicate' in again.stdout
    assert (tmp_path/'count').read_text().strip()=='3'


def test_scoped_readiness_preserves_research_failures_and_requires_actual_save():
    import test_autonomy_readiness as fixtures
    from mova_fpl.ops.readiness import evaluate_readiness
    operator=fixtures._operator();operator['runtime']['controls']['delivery_scope']='lineup-v1'
    execution=fixtures._execution()
    execution['delivery']={'live_proof':None}
    kwargs=dict(operator_status=operator,research_coverage={'status':'failed','measured_gameweeks':5,'passing_gameweeks':0},
                execution_status=execution,resilience_evidence=fixtures._resilience(),orchestration_evidence=fixtures._orchestration(),
                alert_channel=fixtures._alert_channel(),alert_channel_evidence=fixtures._alert_channel_drill(),
                alert_channel_live_evidence=fixtures._alert_channel_live(),host_recovery_evidence=None,
                snapshot_rejection_evidence=fixtures._snapshot_rejection(),browser_failure_evidence=fixtures._browser_failure(),
                generated_at='2026-08-30T22:00:00+00:00')
    before=evaluate_readiness(**kwargs)
    assert before['activation']['scope_ready'] is False
    execution['delivery']['live_proof']={'execution_id':'execution_fixture','finished_at':'2026-08-30T21:00:00Z'}
    after=evaluate_readiness(**kwargs)
    assert after['activation']['technical_eligible_level']=='A2' and after['activation']['scope_ready'] is True
    research=next(g for g in after['gates'] if g['code']=='RESEARCH_EVIDENCE_CALIBRATED')
    assert research['status']=='blocked' and research['required_for']==['A3']


def test_live_proof_is_expiring_and_never_closes_the_gameweek(tmp_path):
    service,delivery,pre=seed(tmp_path)
    approval={'cycle_id':'2026-27-gw03','approved_at':NOW.isoformat(),
              'expires_at':(NOW+timedelta(minutes=5)).isoformat()}
    service.db.set_control('delivery_proof',approval,actor='owner',reason='bounded live proof')
    assert delivery.dispatch(actor='timer',reason='normal',now=NOW)['reason']=='expiring_live_proof_in_progress'
    prepared=delivery.dispatch(actor='owner',reason='proof',now=NOW,proof=True)
    eid=prepared['execution_id']
    claim=service.claim(execution_id=eid,actor='owner',reason='proof',now=NOW,lease_seconds=600)
    assert claim['lease_expires_at'].startswith('2026-09-04T16:05:00')
    service.begin(execution_id=eid,claim_token=claim['claim_token'],pre_state=pre,
                  actor='owner',reason='proof',now=NOW)
    post=_private_state(list(range(1,11))+[12,15,11,13,14],captain=7,vice=8,
                        observed_at=NOW+timedelta(seconds=10))
    result=service.finalize(execution_id=eid,claim_token=claim['claim_token'],post_state=post,
                           actor='owner',reason='proof',now=NOW+timedelta(seconds=11))
    assert result['status']=='verified'
    assert service.db.latest_delivery_attempt('2026-27-gw03')['is_delivery_proof']==1
    assert service.db.pending_autonomous_closeout_gws('2026-27')==[]
    assert service.db.seal_verified_decision_cycle('2026-27-gw03',correlation_id='proof',job_id=prepared.get('job_id','proof')) is None
    service.db.set_control('delivery_proof',None,actor='owner',reason='proof ended')
    assert delivery.dispatch(actor='timer',reason='final still due',now=NOW,check_only=True)['status']=='due'


@pytest.mark.parametrize('delta,cycle,ttl', [(-1,'2026-27-gw03',300),(301,'2026-27-gw03',300),
    (1,'2026-27-gw04',300),(1,'2026-27-gw03',3601)])
def test_live_proof_cannot_expand_time_or_cycle(delta,cycle,ttl):
    from mova_fpl.ops.delivery_policy import lineup_proof
    c={'delivery_scope':'lineup-v1','delivery_proof':{'cycle_id':cycle,'approved_at':NOW.isoformat(),
        'expires_at':(NOW+timedelta(seconds=ttl)).isoformat()}}
    assert lineup_proof(c,'2026-27-gw03',NOW+timedelta(seconds=delta)) is False


def test_provisional_lineup_proof_does_not_claim_settlement_or_approved_projection():
    from test_decision_envelope import _bundle,_manifest,_decision,CONTROLS
    from mova_fpl.ops.decision_envelope import build_envelope
    bundle=_bundle(preliminary=True,selected=_decision(captain=2,policy='milp'))
    bundle['engine']['delivery_scope']='lineup-v1'
    manifest=_manifest(phase='baseline',analytics=False)
    controls={**CONTROLS,'delivery_scope':'lineup-v1','delivery_proof':{
        'cycle_id':'2026-27-gw03','approved_at':'2026-09-04T15:00:00Z','expires_at':'2026-09-04T16:00:00Z'}}
    result=build_envelope(bundle=bundle,manifest=manifest,manifest_id='manifest_test',manifest_sha256='a'*64,controls=controls)
    assert result['status']=='staged'
    for code in ['PRIOR_GAMEWEEK_SETTLED','ANALYTICS_APPROVED_CAUSAL']:
        gate=next(g for g in result['validation']['checks'] if g['code']==code)
        assert gate['passed'] is False and gate['severity']=='warning'
    controls['delivery_proof']=None
    assert build_envelope(bundle=bundle,manifest=manifest,manifest_id='manifest_test',manifest_sha256='a'*64,controls=controls)['status']=='blocked'
