"""Weekly delivery on the real ledger; only account observations are fixtures."""
import hashlib
import json
from copy import deepcopy
from datetime import timedelta
from pathlib import Path

import pytest
from test_delivery import seed
from test_execution_attempts import NOW, _private_state
from mova_fpl.data.private_state import seal
from mova_fpl.ops.db import sha256_json
from mova_fpl.ops.decision_envelope import decision_fingerprint
from mova_fpl.ops.progressive_delivery import POLICY
from mova_fpl.ops.unchanged_delivery import closeout_source

CYCLE='2026-27-gw03'
EARLY=NOW+timedelta(minutes=1)
DEADLINE=NOW+timedelta(hours=25,minutes=30)


def weekly_seed(tmp_path):
    service,delivery,pre=seed(tmp_path)
    service.db.upsert_cycle(service.config.season,3,DEADLINE.isoformat(),phase="refresh")
    return service,delivery,pre
TARGET=list(range(1,11))+[12,15,11,13,14]


def publish(service,state,now,*,captain=7,vice=8,order=TARGET):
    """Publish a new immutable observation, manifest and decision like the normal tick."""
    db=service.db
    state=deepcopy(state);state['event']['deadline_time']=DEADLINE.isoformat();state['observed_at']=(now-timedelta(seconds=1)).isoformat()
    path,m,_=seal(state,service.config.season,service.config.artifact_root/'team_state',expected_team_id=service.config.team_id)
    j,_=db.start_job('tick','source:'+now.isoformat(),'corr',cycle_id=CYCLE)
    q=m['quality']
    tid=db.add_team_state(job_id=j,cycle_id=CYCLE,observed_at=state['observed_at'],source_name='fpl_authenticated_api',
        squad=state['picks'],free_transfers=q['free_transfers'],bank_tenths=q['bank_tenths'],chips=state['chips'],fingerprint=q['fingerprint'],
        artifact_path=str(path),manifest_sha256=hashlib.sha256((path/'manifest.json').read_bytes()).hexdigest())
    original=db.latest_decision_envelope(CYCLE)
    e=json.loads(Path(original['artifact_path']).read_text())
    e.pop('content_sha256');e.pop('envelope_id')
    manifest=db.add_cycle_manifest({'cycle_id':CYCLE,'as_of_at':now.isoformat(),'deadline_at':DEADLINE.isoformat(),
        'phase':'refresh','team_state_id':tid,'plan_id':None,'source_manifest':[],
        'analytics_manifest':{},'research_summary':{},'artifact_path':'fixture'})
    e['manifest']={'manifest_id':manifest['manifest_id'],'content_sha256':manifest['content_sha256']}
    e['team_state']['fingerprint']=q['fingerprint']
    base=e['candidates'][0]['decision']
    current={**base,'starters':[r['element'] for r in state['picks'][:11]],'bench_order':[r['element'] for r in state['picks'][11:]],
        'captain':next(r['element'] for r in state['picks'] if r['is_captain']),
        'vice_captain':next(r['element'] for r in state['picks'] if r['is_vice_captain'])}
    selected={**base,'starters':order[:11],'bench_order':order[11:],'captain':captain,'vice_captain':vice}
    for row,d in zip(e['candidates'],[current,selected]):
        d['fingerprint']=decision_fingerprint(d);row['decision']=d
    sha=sha256_json(e);e.update(content_sha256=sha,envelope_id='envelope_'+sha[:24])
    out=service.config.artifact_root/'decision-envelopes'/(sha+'.json');out.write_text(json.dumps(e))
    db.record_decision_envelope(job_id=j,envelope=e,artifact_path=str(out),artifact_sha256=hashlib.sha256(out.read_bytes()).hexdigest())
    db.finish_job(j,'completed')
    return state


def apply(service,delivery,pre,now,*,captain=7,vice=8,ambiguous=False):
    result=delivery.dispatch(actor='timer',reason='weekly fixture',now=now)
    assert result['status']=='prepared',result
    eid=result['execution_id'];claim=service.claim(execution_id=eid,actor='test',reason='claim',now=now)
    assert claim['status']=='claimed',claim
    service.begin(execution_id=eid,claim_token=claim['claim_token'],pre_state=pre,actor='test',reason='begin',now=now)
    post=_private_state(TARGET,captain=captain,vice=vice,observed_at=now+timedelta(seconds=10))
    post['event']['deadline_time']=DEADLINE.isoformat()
    if ambiguous:
        service.fail(execution_id=eid,claim_token=claim['claim_token'],ambiguous=True,actor='test',reason='lost reply',error_code='LOST',error_detail='fixture',now=now)
    else:
        assert service.finalize(execution_id=eid,claim_token=claim['claim_token'],post_state=post,actor='test',reason='reload',now=now+timedelta(seconds=11))['status']=='verified'
    return eid,post


def test_weekly_initial_save_next_revision_and_final_confirmation(tmp_path):
    service,delivery,pre=weekly_seed(tmp_path)
    service.db.set_control('delivery_policy',POLICY,actor='owner',reason='weekly authorization')
    pre=publish(service,pre,EARLY)
    first,post=apply(service,delivery,pre,EARLY)
    assert service.db.status()['cycle']['status']!='executed_verified'
    assert service.status()['delivery']['final_receipt'] is None
    assert service.db.pending_autonomous_closeout_gws(service.config.season)==[]
    assert delivery.dispatch(actor='timer',reason='replay',now=EARLY+timedelta(seconds=20))['reason']=='delivery_review_cadence'
    later=EARLY+timedelta(hours=2)
    pre=publish(service,post,later,captain=9)
    second,post=apply(service,delivery,pre,later,captain=9)
    assert second!=first
    assert service.db.latest_delivery_verification(CYCLE)['stage']=='provisional'
    final=DEADLINE-timedelta(minutes=90)
    publish(service,post,final,captain=9)
    result=delivery.dispatch(actor='timer',reason='final unchanged',now=final)
    assert result['status']=='unchanged_verified',result
    receipt=service.status()['delivery']['final_receipt']
    assert receipt['job_id']==result['job_id'] and receipt['status']=='unchanged_verified'
    assert closeout_source(service.config,service.db,CYCLE)['execution_id']==result['job_id']
    assert service.db.pending_autonomous_closeout_gws(service.config.season)==[3]


def test_old_verified_save_never_masks_new_ambiguous_revision(tmp_path):
    service,delivery,pre=weekly_seed(tmp_path)
    service.db.set_control('delivery_policy',POLICY,actor='owner',reason='weekly authorization')
    pre=publish(service,pre,EARLY);_,post=apply(service,delivery,pre,EARLY)
    later=EARLY+timedelta(hours=2);pre=publish(service,post,later,captain=9)
    eid,_=apply(service,delivery,pre,later,captain=9,ambiguous=True)
    again=delivery.dispatch(actor='timer',reason='must not retry',now=later+timedelta(hours=2))
    assert again['status']=='ambiguous' and again['execution_id']==eid
    assert service.db.final_delivery_verification(CYCLE) is None


def test_policy_revocation_after_prepare_blocks_claim(tmp_path):
    service,delivery,pre=weekly_seed(tmp_path)
    service.db.set_control('delivery_policy',POLICY,actor='owner',reason='weekly authorization')
    publish(service,pre,EARLY)
    result=delivery.dispatch(actor='timer',reason='prepare',now=EARLY)
    service.db.set_control('delivery_policy',None,actor='owner',reason='pause')
    claim=service.claim(execution_id=result['execution_id'],actor='test',reason='claim',now=EARLY)
    assert claim['status']=='blocked' and 'DELIVERY_POLICY_CHANGED' in claim['blocking_codes']


@pytest.mark.parametrize('seconds',[72*3600+1,30*60,15*60,0])
def test_weekly_bounds_still_fail_closed(tmp_path,seconds):
    service,delivery,_=weekly_seed(tmp_path)
    service.db.set_control('delivery_policy',POLICY,actor='owner',reason='weekly authorization')
    deadline=DEADLINE
    assert delivery.dispatch(actor='timer',reason='boundary',now=deadline-timedelta(seconds=seconds))['status']=='not_due'


def test_final_physical_save_does_not_stop_later_solves_or_hide_new_confirmation(tmp_path):
    service,delivery,pre=weekly_seed(tmp_path)
    service.db.set_control('delivery_policy',POLICY,actor='owner',reason='weekly authorization')
    final=DEADLINE-timedelta(hours=2)
    pre=publish(service,pre,final)
    first,post=apply(service,delivery,pre,final)
    assert service.db.seal_verified_decision_cycle(CYCLE,correlation_id='fixture',job_id='fixture') is None
    assert service.status()['delivery']['final_receipt']['execution_id']==first
    later=final+timedelta(minutes=10)
    publish(service,post,later)
    noop=delivery.dispatch(actor='timer',reason='latest final confirmation',now=later)
    assert noop['status']=='unchanged_verified'
    assert service.status()['delivery']['final_receipt']['job_id']==noop['job_id']
    assert closeout_source(service.config,service.db,CYCLE)['execution_id']==noop['job_id']


def test_new_decision_invalidates_old_prepared_revision(tmp_path):
    service,delivery,pre=weekly_seed(tmp_path)
    service.db.set_control('delivery_policy',POLICY,actor='owner',reason='weekly authorization')
    pre=publish(service,pre,EARLY)
    old=delivery.dispatch(actor='timer',reason='prepare',now=EARLY)
    publish(service,pre,EARLY+timedelta(seconds=1),captain=9)
    claim=service.claim(execution_id=old['execution_id'],actor='test',reason='stale revision',now=EARLY+timedelta(seconds=1))
    assert claim['status']=='blocked' and 'DELIVERY_DECISION_SUPERSEDED' in claim['blocking_codes']


def test_provisional_unchanged_receipt_never_qualifies_for_closeout(tmp_path):
    service,delivery,pre=weekly_seed(tmp_path)
    service.db.set_control('delivery_policy',POLICY,actor='owner',reason='weekly authorization')
    state=_private_state(TARGET,captain=7,vice=8,observed_at=EARLY)
    publish(service,state,EARLY)
    assert delivery.dispatch(actor='timer',reason='already correct',now=EARLY)['status']=='unchanged_verified'
    assert service.db.delivery_receipt(CYCLE) is None
    assert service.db.final_delivery_verification(CYCLE) is None
    assert service.db.pending_autonomous_closeout_gws(service.config.season)==[]
    assert closeout_source(service.config,service.db,CYCLE) is None
