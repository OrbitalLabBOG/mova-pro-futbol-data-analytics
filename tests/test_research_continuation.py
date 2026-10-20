"""Real request/import/resume ledger, fixture-only HTTPS evidence, no model calls."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import pytest
from test_strategic_context import _runtime, _plan
from test_research_evidence import _v2_result, _fetcher
from mova_fpl.ops.strategy import StrategicContextService
from mova_fpl.ops.research_continuation import POLICY, assess


def setup(tmp_path):
    config,db,_,cycle=_runtime(tmp_path)
    service=StrategicContextService(config,db,evidence_fetcher=_fetcher(config.research_root))
    service.activate_plan(_plan(),actor='test',reason='fixture')
    return config,db,service,cycle


def finish(config,db,service,cycle,queued,covered):
    run=db.research_run(queued['research_run_id']);request=json.loads(Path(run['request_path']).read_text())
    result=_v2_result(run,cycle,request['manifest']['research_summary']['focus'])
    result['signals']=[]
    for row in result['coverage']['subjects']:
        row['status']='no_material_update'
        if row['player_element'] not in covered:row.update(status='not_checked',source_urls=[],note='Pending club')
    out=config.research_root/'outbox'/f"{run['research_run_id']}.result.json";out.parent.mkdir(exist_ok=True,parents=True);out.write_text(json.dumps(result))
    imported=service.import_ready()
    assert imported['processed']==1
    assert imported['results'][0]['status']=='imported', imported
    return db.research_run(run['research_run_id'])


def test_scheduler_resumes_exact_pending_focus_and_stops_after_verified_completion(tmp_path):
    config,db,service,cycle=setup(tmp_path)
    first=service.enqueue();run=finish(config,db,service,cycle,first,{1,2,3})
    before=db.research_coverage()['latest']['coverage']['evidence_verified_subjects']
    assert before==3
    due=service.due();assert due['due'] and due['reason']=='completion_pending'
    assert set(due['continuation']['pending_subjects'])==set(range(4,16))
    second=service.enqueue();request=json.loads(Path(second['request_path']).read_text())
    assert request['continuation']['parent_run_id']==first['research_run_id']
    assert request['completion_policy']==POLICY
    assert service.enqueue()['reason']=='previous_run_not_terminal'
    finish(config,db,service,cycle,second,set(range(1,16)))
    assert service.due()['reason']=='research_focus_complete'
    assert db.research_run(first['research_run_id'])['coverage_json']==run['coverage_json']
    assert db.research_coverage()['latest']['coverage']['evidence_verified_subjects']==15
    with db.connect(readonly=True) as con:assert con.execute('SELECT COUNT(*) FROM research_runs').fetchone()[0]==2


@pytest.mark.parametrize('condition,reason',[('budget','completion_budget_reserved'),('limit','completion_slot_limit'),('deadline','completion_deadline_reserve'),('artifact','completion_parent_artifact_invalid')])
def test_resume_stops_with_real_reason_and_preserves_pending(tmp_path,monkeypatch,condition,reason):
    config,db,service,cycle=setup(tmp_path)
    first=service.enqueue();run=finish(config,db,service,cycle,first,{1})
    if condition=='budget':monkeypatch.setattr(db,'cost_report',lambda *a,**k:{'status':'blocked'})
    if condition=='artifact':Path(run['result_path']).write_text('{}')
    decision=assess(config,db,run,count=3 if condition=='limit' else 1,run_kind='broad',
                    seconds=config.research_final_cutoff_seconds+10 if condition=='deadline' else 40000)
    assert decision['due'] is False and decision['reason']==reason
    assert db.research_run(run['research_run_id'])['status']=='imported'


def test_failed_attempt_never_becomes_a_completion_retry(tmp_path):
    config,db,service,cycle=setup(tmp_path)
    first=service.enqueue();run=db.research_run(first['research_run_id'])
    db.reject_research_run(run['research_run_id'],error_code='authentication',error_detail='fixture')
    assert service.due()['reason']=='slot_already_attempted'
    assert assess(config,db,{**run,'status':'failed'},count=1,run_kind='broad',seconds=40000) is None


def test_resume_rejects_modified_parent_request(tmp_path):
    config,db,service,cycle=setup(tmp_path)
    first=service.enqueue();run=finish(config,db,service,cycle,first,{1})
    path=config.research_root/'archive'/Path(run['request_path']).name
    request=json.loads(path.read_text());request['completion_policy']['max_runs_per_slot']=100
    path.write_text(json.dumps(request))
    assert service.due()['reason']=='completion_parent_request_invalid'


def test_manual_resume_uses_same_parent_outside_regular_window_and_cannot_duplicate_child(tmp_path):
    from datetime import timedelta
    config,db,service,cycle=setup(tmp_path)
    first=service.enqueue();finish(config,db,service,cycle,first,{1,2,3})
    with db.transaction() as con:
        con.execute('UPDATE gameweek_cycles SET deadline_at=? WHERE cycle_id=?',
                    ((datetime.now(timezone.utc)+timedelta(days=3)).isoformat(),cycle))
    assert service.due()['reason']=='outside_research_window'
    child=service.enqueue(force=True,actor='owner',reason='authorized completion test',
                          idempotency_key='manual-child',resume_run_id=first['research_run_id'])
    request=json.loads(Path(child['request_path']).read_text())
    assert request['continuation']['parent_run_id']==first['research_run_id']
    assert request['continuation']['round']==2
    assert set(request['continuation']['pending_subjects'])==set(range(4,16))
    replay=service.enqueue(force=True,actor='owner',reason='replay',idempotency_key='another-key',
                           resume_run_id=first['research_run_id'])
    assert replay['reused'] and replay['research_run_id']==child['research_run_id']
    with pytest.raises(ValueError,match='audited --force'):
        service.enqueue(resume_run_id=first['research_run_id'])
    with pytest.raises(ValueError,match='current cycle'):
        service.enqueue(force=True,actor='owner',reason='bad parent',idempotency_key='wrong',resume_run_id='missing')
