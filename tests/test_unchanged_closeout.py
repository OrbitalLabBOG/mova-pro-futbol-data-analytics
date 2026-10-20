"""Authenticated fixture -> dispatch receipt -> financed closeout, without browser writes."""
import hashlib
import json
from datetime import timedelta
from pathlib import Path
import pytest

from test_delivery import seed
from test_execution_attempts import _private_state, NOW
from mova_fpl.data.private_state import seal
from mova_fpl.ops.decision_envelope import decision_fingerprint
from mova_fpl.ops.db import sha256_json
from mova_fpl.ops.review import GameweekReviewService
from mova_fpl.ops.unchanged_delivery import closeout_source


def noop(tmp_path, *, proof=False):
    service, delivery, _ = seed(tmp_path)
    db = service.db
    state = _private_state([1,2,3,4,5,7,8,9,10,12,13,15,6,11,14], captain=7, vice=8,
                           observed_at=NOW-timedelta(seconds=10))
    path, manifest, _ = seal(state, service.config.season, service.config.artifact_root/'team_state',
                            expected_team_id=service.config.team_id)
    job, _ = db.start_job('tick', 'noop-source', 'corr', cycle_id='2026-27-gw03')
    q=manifest['quality']
    tid=db.add_team_state(job_id=job,cycle_id='2026-27-gw03',observed_at=state['observed_at'],
        source_name='fpl_authenticated_api',squad=state['picks'],free_transfers=q['free_transfers'],
        bank_tenths=q['bank_tenths'],chips=state['chips'],fingerprint=q['fingerprint'],
        artifact_path=str(path),manifest_sha256=hashlib.sha256((path/'manifest.json').read_bytes()).hexdigest())
    old=db.latest_decision_envelope('2026-27-gw03')
    e=json.loads(Path(old['artifact_path']).read_text());e.pop('content_sha256');e.pop('envelope_id')
    with db.transaction() as con:
        con.execute('UPDATE cycle_manifests SET team_state_id=? WHERE manifest_id=?',(tid,e['manifest']['manifest_id']))
    d={**e['candidates'][0]['decision'],'starters':[r['element'] for r in state['picks'][:11]],
       'bench_order':[r['element'] for r in state['picks'][11:]],'captain':7,'vice_captain':8}
    d['fingerprint']=decision_fingerprint(d)
    for c in e['candidates']:c['decision']=d.copy()
    e['team_state']['fingerprint']=q['fingerprint'];sha=sha256_json(e)
    e.update(envelope_id='envelope_'+sha[:24],content_sha256=sha)
    target=service.config.artifact_root/'decision-envelopes'/'noop.json';target.write_text(json.dumps(e))
    db.record_decision_envelope(job_id=job,envelope=e,artifact_path=str(target),artifact_sha256=hashlib.sha256(target.read_bytes()).hexdigest())
    db.finish_job(job,'completed')
    result=delivery.dispatch(actor='test',reason='authenticated no-op',now=NOW)
    assert result['status']=='unchanged_verified'
    return service,delivery,result,state


def test_noop_receipt_is_durable_idempotent_and_not_physical_save(tmp_path):
    service, delivery, result, state=noop(tmp_path)
    source=closeout_source(service.config,service.db,'2026-27-gw03')
    assert source['execution_id']==result['job_id']
    assert service.db.pending_autonomous_closeout_gws('2026-27')==[3]
    assert service.db.latest_delivery_proof(service.config.git_sha) is None
    assert service.db.latest_delivery_attempt('2026-27-gw03') is None
    receipt=json.loads(Path(source['evidence_path']).read_text())
    assert receipt['physical_save'] is False and receipt['delivery_proof'] is False
    again=delivery.dispatch(actor='test',reason='replay',now=NOW)
    assert again['job_id']==result['job_id']


@pytest.mark.parametrize('tamper',['receipt','state','plan','proof'])
def test_noop_closeout_rejects_tampered_or_proof_evidence(tmp_path,tamper):
    service,_,_,_=noop(tmp_path)
    source=closeout_source(service.config,service.db,'2026-27-gw03')
    if tamper=='receipt':Path(source['evidence_path']).write_text('{}')
    elif tamper=='state':
        with service.db.connect(readonly=True) as con:r=con.execute('SELECT artifact_path FROM team_state_snapshots WHERE team_state_id=?',(source['receipt_team_state_id'],)).fetchone()
        Path(r[0],'manifest.json').write_text('{}')
    elif tamper=='proof':
        with service.db.transaction() as con:con.execute("UPDATE job_runs SET metrics_json=json_set(metrics_json,'$.delivery_proof',1) WHERE job_id=?",(source['execution_id'],))
        assert closeout_source(service.config,service.db,'2026-27-gw03') is None
        assert service.db.pending_autonomous_closeout_gws('2026-27')==[]
        return
    else:
        row=service.db.execution_claim_source(json.loads(service.db.delivery_receipt('2026-27-gw03')['metrics_json'])['plan_id'])['plan']
        Path(row['artifact_path']).write_text('{}')
    with pytest.raises((RuntimeError,ValueError)):closeout_source(service.config,service.db,'2026-27-gw03')


def test_noop_builds_financed_package_with_duplicate_equal_candidates(tmp_path,monkeypatch):
    service,_,_,state=noop(tmp_path)
    class Connection:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def execute(self,query,params):
            if 'model_projection_batches' in query:self.rows=[{'batch_id':'projection_fixture','input_artifact_id':'artifact_pre','cutoff_at':NOW.isoformat()}]
            else:self.rows=[{'element':r['element'],'player_name':str(r['element']),'team':'Club'+str(r['element']%5),
              'position':{1:'GKP',2:'DEF',3:'MID',4:'FWD'}[r['element_type']],'xp':3,'p_60':0.9,'now_cost':50} for r in state['picks']]
            return self
        def fetchall(self):return self.rows
    monkeypatch.setattr('mova_fpl.ops.review.connect',lambda *a,**k:Connection())
    p=GameweekReviewService(service.config,service.db)._autonomous_package(gw=3)
    result=json.loads(p.read_text())
    assert result['verified_execution_source']=='unchanged_delivery'
    assert result['selected']['captain']==7
    assert result['selected']['financing']['bank_after_tenths']==10
    assert result['selected']['financing']['after']==result['comparator']['financing']['before']
