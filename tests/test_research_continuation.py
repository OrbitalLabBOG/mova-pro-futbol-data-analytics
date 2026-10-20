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
from mova_fpl.ops.research_campaign import progress
from mova_fpl.ops.research_evidence import SafeEvidenceFetcher


def setup(tmp_path):
    config,db,_,cycle=_runtime(tmp_path)
    names=' '.join('Player '+str(i)+'.' for i in range(1,16))+' Available for selection.'
    day=datetime.now(timezone.utc).date().isoformat()
    def transport(url):
        return (('<html><time datetime="'+day+'T00:00:00+00:00">'+day+'</time><body>'+names+'</body></html>').encode(),
                {'content_type':'text/html','http_status':200,'final_url':url})
    service=StrategicContextService(config,db,evidence_fetcher=SafeEvidenceFetcher(config.research_root,transport=transport))
    focus=[{'element':i,'player_name':'Player '+str(i),'team':'Club','position':'MID',
            'official_status':'a','official_chance_next':100,'official_news':None,
            'focus_reason':['current_squad']} for i in range(1,16)]
    service._test_focus=focus
    service._research_focus=lambda *a,**k:focus
    service._research_world=lambda **k:{'status':'ready','catalog':[[i,'Player '+str(i),'Club'] for i in range(1,16)]}
    service._test_excerpt=names
    service.activate_plan(_plan(),actor='test',reason='fixture')
    return config,db,service,cycle


def finish(config,db,service,cycle,queued,covered,uncertain=()):
    run=db.research_run(queued['research_run_id']);request=json.loads(Path(run['request_path']).read_text())
    result=_v2_result(run,cycle,request['manifest']['research_summary']['focus'])
    result['signals']=[]
    for doc in result['documents']:
        doc['published_at']=datetime.now(timezone.utc).date().isoformat()+'T00:00:00+00:00'
        doc['evidence_text']=service._test_excerpt
    for row in result['coverage']['subjects']:
        row['status']='unresolved' if row['player_element'] in uncertain else 'no_material_update'
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
    finish(config,db,service,cycle,second,set(range(4,16)))
    assert service.due()['reason']=='research_focus_complete'
    assert db.research_run(first['research_run_id'])['coverage_json']==run['coverage_json']
    assert db.research_coverage()['latest']['coverage']['evidence_verified_subjects']==12
    campaign=progress(config,db,cycle)
    assert campaign['status']=='complete' and campaign['verified_subjects']==15
    assert campaign['acceptance_eligible'] is False and campaign['permits_execution'] is False
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


@pytest.mark.parametrize('condition',['news','stale','artifact'])
def test_accumulated_progress_invalidates_changed_expired_or_tampered_evidence(tmp_path,condition):
    from datetime import timedelta
    config,db,service,cycle=setup(tmp_path)
    first=service.enqueue();finish(config,db,service,cycle,first,set(range(1,16)))
    assert progress(config,db,cycle)['status']=='complete'
    if condition=='news':
        service._test_focus[0]['official_news']='New injury update'
        service.prepare()
        report=progress(config,db,cycle)
        assert report['pending_subjects']==[1]
    elif condition=='stale':
        report=progress(config,db,cycle,now=datetime.now(timezone.utc)+timedelta(days=8))
        assert report['verified_subjects']==0
    else:
        with db.connect(readonly=True) as con:path=con.execute('SELECT artifact_path FROM research_documents LIMIT 1').fetchone()[0]
        Path(path).write_text('{}')
        assert progress(config,db,cycle)['verified_subjects']==0


def test_newer_uncertainty_cannot_be_hidden_by_older_positive_evidence(tmp_path):
    config,db,service,cycle=setup(tmp_path)
    first=service.enqueue();finish(config,db,service,cycle,first,set(range(1,16)))
    second=service.enqueue(force=True,actor='owner',reason='new material uncertainty',idempotency_key='uncertain')
    finish(config,db,service,cycle,second,set(range(1,16)),uncertain={1})
    report=progress(config,db,cycle)
    assert report['verified_subjects']==15 and report['completed_subjects']==14
    assert report['pending_subjects']==[1] and report['status']=='partial'


def test_next_regular_slot_keeps_partial_work_and_still_runs_its_refresh(tmp_path):
    from datetime import timedelta
    config,db,service,cycle=setup(tmp_path)
    first=service.enqueue();finish(config,db,service,cycle,first,{1,2,3})
    due=service.due(now=datetime.now(timezone.utc)+timedelta(hours=7))
    assert due['due'] and due['run_kind']=='refresh'
    assert due['continuation']['parent_run_id']==first['research_run_id']
    assert due['continuation']['round']==1
    assert due['continuation']['pending_subjects']==list(range(4,16))
