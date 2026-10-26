"""A manual receipt protects one GW without disabling next week's scheduler."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import pytest

from test_manual_verified import _package, _runtime
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.delivery import DeliveryService
from mova_fpl.ops.execution import ExecutionService
from mova_fpl.ops.manual_delivery import hold, receipt
from mova_fpl.ops.supervised import record


def test_manual_v2_holds_cycle_and_next_cycle_resumes_without_control_write(tmp_path, monkeypatch):
    package, _ = _package(tmp_path)
    db = _runtime(monkeypatch, tmp_path)
    for k,v in {'delivery_scope':'lineup-v1','delivery_policy':'progressive-lineup-v1',
                'action_level':'A2','mode':'autonomous','kill_switch':False,
                'browser_writes':True,'compliance_gate':'approved'}.items():
        db.set_control(k,v,actor='owner',reason='permanent bounded authority')
    record(package,actor='owner',reason='manual override',idempotency_key='manual')
    config=RuntimeConfig.from_env()
    before=db.controls()
    d=DeliveryService(config,db)
    now=datetime(2026,9,18,17,0,tzinfo=timezone.utc)
    assert d.dispatch(actor='timer',reason='must hold',now=now)['reason']=='manual_cycle_hold'
    assert receipt(config,db,'2026-27-gw05')['status']=='manual_verified'
    assert ExecutionService(config,db).status()['delivery']['final_receipt'] is None
    assert ExecutionService(config,db).status()['delivery']['manual_receipt']['scheduler_save'] is False
    assert db.seal_verified_decision_cycle('2026-27-gw05',correlation_id='test',job_id='test')
    db.upsert_cycle('2026-27',6,'2026-09-25T17:30:00Z',phase='baseline')
    assert d.dispatch(actor='timer',reason='next GW',now=now)['reason']=='outside_delivery_window'
    assert hold(db,'2026-27-gw06') is None
    assert db.controls()==before


def test_tampered_manual_evidence_never_releases_hold(tmp_path,monkeypatch):
    package, body=_package(tmp_path)
    db=_runtime(monkeypatch,tmp_path)
    record(package,actor='owner',reason='manual override',idempotency_key='manual')
    Path(body['execution']['evidence_path']).write_text('tampered')
    assert receipt(RuntimeConfig.from_env(),db,'2026-27-gw05') is None
    assert hold(db,'2026-27-gw05') is not None


def test_manual_receipt_satisfies_watchdog_without_fabricating_native_receipt(tmp_path,monkeypatch):
    from mova_fpl.ops.watchdog import assess_workflow_deadline
    package,_=_package(tmp_path);db=_runtime(monkeypatch,tmp_path)
    db.set_control('delivery_scope','lineup-v1',actor='owner',reason='bounded')
    record(package,actor='owner',reason='manual',idempotency_key='manual')
    monkeypatch.setattr('mova_fpl.ops.orchestration.build_workflow',lambda *a,**k:{'stages':[],'violations':[]})
    result=assess_workflow_deadline(RuntimeConfig.from_env(),db,now=datetime(2026,9,18,18,tzinfo=timezone.utc))
    assert not any(r['code']=='bounded_team_delivery_not_verified' for r in result['reasons'])
    assert db.final_delivery_verification('2026-27-gw05') is None


@pytest.mark.parametrize('claimed',[False,True])
def test_native_claim_and_manual_import_cannot_cross_each_other(tmp_path,monkeypatch,claimed):
    from test_delivery import seed
    from test_execution_attempts import NOW
    from mova_fpl.data.private_state import validate
    service,delivery,_=seed(tmp_path)
    prepared=delivery.dispatch(actor='timer',reason='prepare before override',now=NOW)
    if claimed:
        service.claim(execution_id=prepared['execution_id'],actor='timer',reason='claim',now=NOW)
    package,body=_package(tmp_path/'manual')
    body['gw']=3;body['cycle_id']='2026-27-gw03'
    for key in ('pre_team_state','post_team_state'):
        path=Path(body[key]['artifact_path'])/'team-state.json'
        state=json.loads(path.read_text());state['event']['id']=3
        path.write_text(json.dumps(state))
        _,quality=validate(state)
        body[key]['payload_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        body[key]['fingerprint']=quality['fingerprint']
    body['decision']['fingerprint']=body['post_team_state']['fingerprint']
    package.write_text(json.dumps(body))
    monkeypatch.setenv('MOVA_OPS_DB',str(service.config.ops_db))
    monkeypatch.setenv('MOVA_ARTIFACT_ROOT',str(tmp_path))
    monkeypatch.setenv('MOVA_SQLITE_MIN_VERSION','3.0.0')
    if claimed:
        with pytest.raises(RuntimeError,match='active or ambiguous'):
            record(package,actor='owner',reason='manual override',idempotency_key='manual-race')
    else:
        record(package,actor='owner',reason='manual override',idempotency_key='manual-race')
        # Model the race after a successful service-level read, before DB CAS.
        with pytest.raises(RuntimeError,match='MANUAL_CYCLE_HOLD'):
            service.db.claim_execution_attempt(execution_id=prepared['execution_id'],token_sha256='f'*64,
                claimant='timer',reason='stale check',claimed_at=NOW.isoformat(),
                lease_expires_at='2026-09-04T16:05:00Z')
