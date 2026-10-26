"""All operational runs count; a partial start is not a failed campaign."""
import hashlib
import json
from datetime import datetime,timedelta,timezone
from pathlib import Path

import pytest
from test_research_acceptance import _cohort,_run,_passing
from mova_fpl.ops.db import sha256_json
from mova_fpl.ops.research_campaign_acceptance import slot_report


def imported(config,db,manifest,prepared,gw,kind,*,suffix):
    run_id=_run(config,db,manifest,prepared,gw,suffix=suffix)
    body={'research_run_id':run_id,'cycle_id':f'{config.season}-gw{gw:02d}',
          'run_kind':kind,'acceptance_contract':manifest['contract'],
          'manifest':{'cycle_id':f'{config.season}-gw{gw:02d}',
                      'deadline_at':next(s['deadline_at'] for s in manifest['slots'] if s['gw']==gw)}}
    body['request_sha256']=sha256_json(body)
    root=config.research_root;root.mkdir(parents=True,exist_ok=True)
    request=root/f'{run_id}.request.json';request.write_text(json.dumps(body))
    result=root/f'{run_id}.result.json';result.write_text('{}')
    with db.transaction() as con:
        con.execute('UPDATE research_runs SET request_path=?,request_sha256=?,result_path=?,result_sha256=? WHERE research_run_id=?',
                    (str(request),body['request_sha256'],str(result),hashlib.sha256(result.read_bytes()).hexdigest(),run_id))
    _passing(db,manifest,run_id)
    if kind in {'refresh','final'}:
        deadline=datetime.fromisoformat(next(s['deadline_at'] for s in manifest['slots'] if s['gw']==gw))
        queued=deadline-timedelta(hours=5 if kind=='refresh' else 1.5)
        with db.transaction() as con:
            con.execute('UPDATE research_runs SET queued_at=?,imported_at=? WHERE research_run_id=?',
                        (queued.isoformat(),(queued+timedelta(seconds=2)).isoformat(),run_id))
            con.execute('UPDATE agent_worker_attempt_events SET occurred_at=? WHERE subject_id=?',
                        ((queued+timedelta(seconds=1)).isoformat(),run_id))
    return run_id


def quality(monkeypatch,processed=15,verified=15):
    monkeypatch.setattr('mova_fpl.ops.research_campaign_acceptance.progress',lambda *a,**k:{
        'required_subjects':15,'processed_subjects':processed,'verified_subjects':verified,
        'pending_subjects':[]})


def test_partial_first_run_accumulates_and_requires_final_refreshes(tmp_path,monkeypatch):
    config,db,manifest,_,prepared=_cohort(tmp_path,monkeypatch,campaign=True)
    first=imported(config,db,manifest,prepared,2,'broad',suffix='a')
    with db.transaction() as con:
        con.execute('UPDATE research_runs SET coverage_ratio=.2,evidence_ratio=.2 WHERE research_run_id=?',(first,))
    quality(monkeypatch,3,3)
    now=datetime.now(timezone.utc)
    slot=slot_report(db,config,manifest,manifest['slots'][0],now=now)
    assert slot['status']=='pending' and not slot['reasons']
    quality(monkeypatch)
    expired=datetime.fromisoformat(manifest['slots'][0]['deadline_at'])+timedelta(seconds=1)
    assert slot_report(db,config,manifest,manifest['slots'][0],now=expired)['reasons']==['mandatory_refresh_missing']
    imported(config,db,manifest,prepared,2,'refresh',suffix='b')
    imported(config,db,manifest,prepared,2,'final',suffix='c')
    slot=slot_report(db,config,manifest,manifest['slots'][0],now=expired)
    assert slot['status']=='passed' and len(slot['research_run_ids'])==3
    assert slot['research_run_id']==first


@pytest.mark.parametrize('problem',['failed','conservative','tampered','drift','late'])
def test_later_success_never_hides_failed_or_uncertain_run(tmp_path,monkeypatch,problem):
    config,db,manifest,_,prepared=_cohort(tmp_path,monkeypatch,campaign=True)
    run=imported(config,db,manifest,prepared,2,'broad',suffix='a')
    imported(config,db,manifest,prepared,2,'refresh',suffix='b')
    imported(config,db,manifest,prepared,2,'final',suffix='c')
    with db.transaction() as con:
        if problem=='failed':con.execute("UPDATE agent_worker_attempt_events SET status='failed',error_code='fixture' WHERE subject_id=? AND event_type='finished'",(run,))
        if problem=='conservative':con.execute("UPDATE agent_budget_reservations SET accounting_mode='conservative' WHERE subject_id=?",(run,))
        if problem=='late':con.execute('UPDATE research_runs SET imported_at=? WHERE research_run_id=?',((datetime.fromisoformat(manifest['slots'][0]['deadline_at'])+timedelta(seconds=1)).isoformat(),run))
    path=Path(db.research_run(run)['request_path'])
    if problem=='tampered':path.write_text('{}')
    if problem=='drift':
        body=json.loads(path.read_text());body['acceptance_contract']={}
        body['request_sha256']=sha256_json({k:v for k,v in body.items() if k!='request_sha256'})
        path.write_text(json.dumps(body))
        with db.transaction() as con:
            con.execute('UPDATE research_runs SET request_sha256=? WHERE research_run_id=?',(body['request_sha256'],run))
    quality(monkeypatch)
    after=datetime.fromisoformat(manifest['slots'][0]['deadline_at'])+timedelta(seconds=1)
    report=slot_report(db,config,manifest,manifest['slots'][0],now=after)
    assert report['status']=='failed' and len(report['research_run_ids'])==3


def test_campaign_cohort_does_not_reinterpret_legacy_or_pass_early(tmp_path,monkeypatch):
    config,db,manifest,_,prepared=_cohort(tmp_path,monkeypatch,campaign=True)
    imported(config,db,manifest,prepared,2,'broad',suffix='a');quality(monkeypatch)
    report=db.research_acceptance(config)
    assert report['status']=='in_progress'
    assert report['active']['evaluation']=='campaign-v2'
    assert report['historical']==db.research_coverage()
