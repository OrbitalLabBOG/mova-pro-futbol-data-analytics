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


def test_completion_context_keeps_only_pending_hints_without_copying_bodies():
    from mova_fpl.ops.research_continuation import pending_brief
    body={'documents':[{'source_url':'https://club.test/done','evidence_text':'x'*10000},
                       {'source_url':'https://club.test/pending','title':'Update','evidence_text':'y'*10000}],
          'coverage':{'subjects':[{'player_element':1,'source_urls':['https://club.test/done']},
                                  {'player_element':2,'source_urls':['https://club.test/pending']}]},
          'signals':[{'player_element':1},{'player_element':2}], 'conflicts':[]}
    hints=pending_brief(body,[2])
    assert hints['documents']==[{'source_url':'https://club.test/pending','title':'Update'}]
    assert hints['signals']==[{'player_element':2}]
    assert hints['evidence_requires_new_read'] is True
    assert len(body['documents'][0]['evidence_text'])==10000


def test_as_of_campaign_does_not_use_post_cutoff_manifest_or_import(tmp_path):
    from datetime import timedelta
    config,db,service,cycle=setup(tmp_path)
    first=service.enqueue();finish(config,db,service,cycle,first,set(range(1,16)))
    cutoff=datetime.now(timezone.utc)
    manifest=db.latest_cycle_manifest(cycle)
    manifest['as_of_at']=(cutoff+timedelta(hours=1)).isoformat()
    manifest['research_summary']['focus'] += [{'element':99,'player_name':'New after cutoff'}]
    db.add_cycle_manifest(manifest)
    report=progress(config,db,cycle,now=cutoff,manifest_as_of=True)
    assert report['required_subjects']==15 and report['verified_subjects']==15
    with db.transaction() as con:
        con.execute('UPDATE research_runs SET imported_at=? WHERE research_run_id=?',
                    ((cutoff+timedelta(seconds=1)).isoformat(),first['research_run_id']))
    assert progress(config,db,cycle,now=cutoff,manifest_as_of=True)['verified_subjects']==0


@pytest.mark.parametrize('condition,reason',[('budget','completion_budget_exhausted'),('deadline','completion_deadline_reserve'),('artifact','completion_parent_artifact_invalid')])
def test_resume_stops_with_real_reason_and_preserves_pending(tmp_path,monkeypatch,condition,reason):
    config,db,service,cycle=setup(tmp_path)
    first=service.enqueue();run=finish(config,db,service,cycle,first,{1})
    if condition=='budget':monkeypatch.setattr(db,'cost_report',lambda *a,**k:{'status':'blocked'})
    if condition=='artifact':Path(run['result_path']).write_text('{}')
    decision=assess(config,db,run,count=4,run_kind='broad',
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
                    ((datetime.now(timezone.utc)+timedelta(days=4)).isoformat(),cycle))
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


def test_continuation_can_use_remaining_budget_without_three_run_or_future_reserve_gate(tmp_path,monkeypatch):
    config,db,service,cycle=setup(tmp_path)
    first=service.enqueue();run=finish(config,db,service,cycle,first,{1,2,3})
    ceiling=config.agent_budget_policy()['job_tokens']
    monkeypatch.setattr(db,'cost_report',lambda *a,**k:{'status':'within_budget',
        'gameweek':{'remaining_tokens':ceiling+1},'month':{'remaining_tokens':ceiling+1}})
    due=assess(config,db,run,count=7,run_kind='broad',seconds=40000)
    assert due['due'] and due['continuation']['round']==8
    assert due['continuation']['unverified_subjects']==list(range(4,16))
    assert due['continuation']['unresolved_subjects']==[]
    assert db.research_run(run['research_run_id'])['status']=='imported'


def test_regular_scheduler_starts_at_72h_without_force_or_owner_validation(tmp_path):
    from datetime import timedelta
    config,db,service,cycle=setup(tmp_path)
    current=datetime.now(timezone.utc)
    with db.transaction() as con:
        con.execute('UPDATE gameweek_cycles SET deadline_at=? WHERE cycle_id=?',
                    ((current+timedelta(hours=70)).isoformat(),cycle))
    due=service.due(now=current)
    assert due['due'] and due['run_kind']=='broad'
    request=service.enqueue()
    assert request['status']=='queued'
    assert json.loads(Path(request['request_path']).read_text())['agent_version']=='1.18.0'
    assert service.due()['reason']=='previous_run_not_terminal'


def test_v1_immutable_parent_can_continue_under_owner_authorized_v2_policy(tmp_path):
    from mova_fpl.ops.research_continuation import LEGACY_POLICY
    config,db,service,cycle=setup(tmp_path)
    first=service.enqueue();run=db.research_run(first['research_run_id'])
    request=json.loads(Path(run['request_path']).read_text());request['completion_policy']=LEGACY_POLICY
    from mova_fpl.ops.db import sha256_json
    request['request_sha256']=sha256_json({k:v for k,v in request.items() if k!='request_sha256'})
    Path(run['request_path']).write_text(json.dumps(request))
    with db.transaction() as con:
        con.execute('UPDATE research_runs SET request_sha256=? WHERE research_run_id=?',
                    (request['request_sha256'],run['research_run_id']))
    run=finish(config,db,service,cycle,first,{1,2,3})
    assert progress(config,db,cycle)['verified_subjects']==3
    assert assess(config,db,run,count=4,run_kind='broad',seconds=40000)['due']


def test_verified_unknown_finishes_investigation_without_claiming_resolution_or_authority(tmp_path):
    from datetime import timedelta
    config,db,service,cycle=setup(tmp_path)
    first=service.enqueue();finish(config,db,service,cycle,first,set(range(1,16)),uncertain={1})
    campaign=progress(config,db,cycle)
    assert campaign['investigation_status']=='complete_with_uncertainty'
    assert campaign['pending_subjects']==[1] and campaign['open_questions']==[1]
    assert campaign['pending_evidence_subjects']==[]
    assert campaign['status']=='partial' and campaign['completed_subjects']==14
    assert campaign['acceptance_eligible'] is False and campaign['permits_execution'] is False
    assert service.due()['reason']=='research_focus_investigated_with_uncertainty'
    refresh=service.due(now=datetime.now(timezone.utc)+timedelta(hours=7))
    assert refresh['due'] and refresh['run_kind']=='refresh'
    assert refresh['continuation']['pending_subjects']==[1]


@pytest.mark.parametrize('remaining,uses',[(159999,1),(160000,0)])
def test_real_token_or_use_exhaustion_still_blocks_new_inference(tmp_path,monkeypatch,remaining,uses):
    config,db,service,cycle=setup(tmp_path)
    first=service.enqueue();run=finish(config,db,service,cycle,first,{1})
    monkeypatch.setattr(db,'cost_report',lambda *a,**k:{'status':'within_budget',
        'gameweek':{'remaining_tokens':remaining,'remaining_uses':uses},
        'month':{'remaining_tokens':1000000,'remaining_uses':1}})
    due=assess(config,db,run,count=7,run_kind='broad',seconds=40000)
    assert not due['due'] and due['reason']=='completion_budget_exhausted'


@pytest.mark.parametrize('hours', [7, 10.25])
def test_new_refresh_slot_cannot_replace_budget_blocked_continuation(tmp_path,monkeypatch,hours):
    from datetime import timedelta
    config,db,service,cycle=setup(tmp_path)
    first=service.enqueue()
    finish(config,db,service,cycle,first,set(range(1,16)),uncertain={1})
    # Enough for the ordinary reservation, but not a complete physical job.
    policy=config.agent_budget_policy()
    monkeypatch.setattr(db,'cost_report',lambda *a,**k:{'status':'within_budget',
        'gameweek':{'remaining_tokens':policy['job_tokens']-1,'remaining_uses':1},
        'month':{'remaining_tokens':1000000,'remaining_uses':1}})
    future=datetime.now(timezone.utc)+timedelta(hours=hours)
    due=service.due(now=future)
    assert not due['due'] and due['reason']=='completion_budget_exhausted'
    assert due['pending_subjects']==[1]
    monkeypatch.setattr(service,'due',lambda:due)
    assert service.enqueue()['status']=='skipped'
    with db.connect(readonly=True) as con:
        assert con.execute('SELECT COUNT(*) FROM research_runs').fetchone()[0]==1


@pytest.mark.parametrize('condition',['replace','same_release','running','tampered','budget'])
def test_corrected_release_replaces_failed_request_without_rewriting_it_or_its_charge(tmp_path,monkeypatch,condition):
    from mova_fpl.ops.agent_releases import researcher_release
    config,db,service,cycle=setup(tmp_path)
    parent=service.enqueue();finish(config,db,service,cycle,parent,{1,2,3})
    if condition!='same_release':
        monkeypatch.setattr('mova_fpl.ops.strategy.researcher_release',lambda *a:researcher_release('1.15.0'))
    old=service.enqueue();old_run=db.research_run(old['research_run_id'])
    original=Path(old_run['request_path']).read_bytes()
    base={'schema':'mova-agent-attempt-v1','attempt_id':'attempt_fixture_rollover',
        'subject_type':'research','subject_id':old['research_run_id'],'request_sha256':old_run['request_sha256'],
        'model':'mock','occurred_at':datetime.now(timezone.utc).isoformat()}
    db.record_agent_worker_attempt_event({**base,'event_type':'started','status':'running'},receipt_path='fixture-start',receipt_sha256='a'*64)
    if condition!='running':
        db.record_agent_worker_attempt_event({**base,'event_type':'finished','status':'failed','error_code':'logical_token_guard'},
            receipt_path='fixture-finish',receipt_sha256='b'*64)
    monkeypatch.undo()
    if condition=='tampered':Path(old_run['request_path']).write_text('{}')
    if condition=='budget':monkeypatch.setattr(db,'cost_report',lambda *a,**k:{'status':'blocked'})
    replacement=service.enqueue()
    if condition in {'same_release','running','tampered'}:
        assert replacement['reason']=='previous_run_not_terminal'
        assert db.research_run(old['research_run_id'])['status']=='queued'
        return
    rejected=db.research_run(old['research_run_id'])
    assert rejected['status']=='rejected' and rejected['error_code']=='research_release_superseded'
    assert rejected['request_sha256']==old_run['request_sha256']
    assert (config.research_root/'quarantine'/Path(old_run['request_path']).name).read_bytes()==original
    if condition=='budget':
        assert replacement['reason']=='completion_budget_exhausted'
        return
    assert replacement['status']=='queued' and replacement['research_run_id']!=old['research_run_id']
    request=json.loads(Path(replacement['request_path']).read_text())
    assert request['agent_version']=='1.18.0'
    assert request['continuation']['parent_run_id']==parent['research_run_id']
    assert replacement['due']['replaces_run_id']==old['research_run_id']
    assert request['continuation']['replaces_run_id']==old['research_run_id']
    assert service.enqueue()['reason']=='previous_run_not_terminal'
    finish(config,db,service,cycle,replacement,set(range(4,16)))
    assert progress(config,db,cycle)['status']=='complete'
    with db.connect(readonly=True) as con:
        assert con.execute('SELECT COUNT(*) FROM agent_worker_attempt_events WHERE subject_id=?',(old['research_run_id'],)).fetchone()[0]==2
        budget=con.execute('SELECT status,accounting_mode FROM agent_budget_reservations WHERE subject_id=?',(old['research_run_id'],)).fetchone()
        assert budget['status']=='charged' and budget['accounting_mode']=='conservative'


def source_activity(config,db,run,element,urls,*,tamper=False,supported=False,ambiguous=False):
    import hashlib
    attempt='attempt_'+hashlib.sha256(run['research_run_id'].encode()).hexdigest()[:32]
    payload={'schema':'mova-agent-attempt-v1','attempt_id':attempt,'subject_type':'research',
        'subject_id':run['research_run_id'],'request_sha256':run['request_sha256'],'event_type':'finished',
        'status':'succeeded','model':'mock','input_tokens':10,'output_tokens':10,
        'occurred_at':datetime.now(timezone.utc).isoformat()}
    path=config.research_root/'receipts'/f"{run['research_run_id']}.{attempt}.finished.json"
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(payload))
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    db.record_agent_worker_attempt_event(payload,receipt_path=str(path),receipt_sha256=digest)
    if tamper:path.write_text('{}')
    log=config.research_root/'logs'/f"{run['research_run_id']}.{attempt}.events.jsonl"
    log.parent.mkdir(parents=True,exist_ok=True)
    events=[{'method':'item/completed','params':{'item':{'type':'mcpToolCall','tool':'read_research_source',
        'status':'failed','arguments':{'source_url':url,'player_elements':[element]},
        'result':{'content':[{'type':'text','text':json.dumps({'status':'rejected','reasons':['source_read_failed']})}]}}}} for url in urls]
    if supported or ambiguous:
        result={'status':'supported','covered_focus_elements':[element]} if supported else {'status':'rejected','reasons':['ambiguous_identity']}
        events.append({'method':'item/completed','params':{'item':{'type':'mcpToolCall','tool':'verify_research_evidence',
            'status':'completed' if supported else 'failed','arguments':{'player_element':element},
            'result':{'content':[{'type':'text','text':json.dumps(result)}]}}}})
    log.write_text(''.join(json.dumps(event)+'\n' for event in events))


@pytest.mark.parametrize('condition',['two_sources','note_only','same_source','tampered_receipt','supported_dropped'])
def test_research_can_finish_with_proven_source_limits_without_manufacturing_coverage(tmp_path,condition):
    from datetime import timedelta
    config,db,service,cycle=setup(tmp_path)
    first=service.enqueue();run=finish(config,db,service,cycle,first,set(range(1,15)))
    if condition!='note_only':
        urls=['https://example.com/report-a','https://example.com/report-b'] if condition!='same_source' else [
            'https://example.com/report?utm=a','https://example.com/report?utm=b']
        source_activity(config,db,run,15,urls,tamper=condition=='tampered_receipt',supported=condition=='supported_dropped')
    report=progress(config,db,cycle)
    assert report['verified_subjects']==14 and report['completed_subjects']==14
    assert report['pending_evidence_subjects']==[15]
    assert report['acceptance_eligible'] is False and report['permits_execution'] is False
    if condition=='two_sources':
        assert report['investigation_status']=='complete_with_limits' and report['processed_subjects']==15
        assert report['source_limited_subjects']==[15] and report['retry_subjects']==[]
        assert service.due()['reason']=='research_focus_investigated_with_limits'
        refreshed=progress(config,db,cycle,now=datetime.now(timezone.utc)+timedelta(hours=7))
        assert refreshed['source_limited_subjects']==[] and refreshed['retry_subjects']==[15]
    else:
        assert report['investigation_status']=='partial' and report['retry_subjects']==[15]


def test_old_duplicate_alias_failure_is_retried_with_corrected_full_identity(tmp_path,monkeypatch):
    from mova_fpl.ops.agent_releases import researcher_release
    config,db,service,cycle=setup(tmp_path)
    service._test_focus[-1]['player_name']='Cole Palmer'
    service._research_world=lambda **k:{'status':'ready','catalog':[[i,'Player '+str(i),'Club'] for i in range(1,15)]+[[15,'Palmer','CHE'],[16,'Palmer','IPS']]}
    monkeypatch.setattr('mova_fpl.ops.strategy.researcher_release',lambda *a:researcher_release('1.16.0'))
    first=service.enqueue();run=finish(config,db,service,cycle,first,set(range(1,15)))
    monkeypatch.undo()
    source_activity(config,db,run,15,['https://example.com/a','https://example.com/b'],ambiguous=True)
    report=progress(config,db,cycle)
    assert report['source_limited_subjects']==[] and report['retry_subjects']==[15]

    # A second legacy run searches but skips verification after seeing the old
    # ambiguity. That newer omission must not hide the original reader defect.
    monkeypatch.setattr('mova_fpl.ops.strategy.researcher_release',lambda *a:researcher_release('1.16.0'))
    second=service.enqueue();second_run=finish(config,db,service,cycle,second,set())
    source_activity(config,db,second_run,15,['https://example.com/c','https://example.com/d'])
    monkeypatch.undo()
    report=progress(config,db,cycle)
    assert report['source_limited_subjects']==[] and report['retry_subjects']==[15]

    # Only a real read with the corrected implementation can end that retry.
    third=service.enqueue();third_run=finish(config,db,service,cycle,third,set())
    source_activity(config,db,third_run,15,['https://example.com/e','https://example.com/f'])
    report=progress(config,db,cycle)
    assert report['source_limited_subjects']==[15] and report['retry_subjects']==[]


def test_continuation_does_not_reopen_attested_source_limits_in_the_same_slot(tmp_path):
    config,db,service,cycle=setup(tmp_path)
    first=service.enqueue();run=finish(config,db,service,cycle,first,set(range(1,14)))
    source_activity(config,db,run,14,['https://example.com/a','https://example.com/b'])
    report=progress(config,db,cycle)
    assert report['source_limited_subjects']==[14] and report['retry_subjects']==[15]
    due=service.due()
    assert due['continuation']['pending_subjects']==[15]
    assert due['continuation']['unverified_subjects']==[15]
