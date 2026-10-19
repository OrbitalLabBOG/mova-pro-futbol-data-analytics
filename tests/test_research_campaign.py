from datetime import datetime,timedelta,timezone

import pytest

from mova_fpl.ops.research_campaign import continuation_gate


def gate(**changes):
    now=datetime(2026,10,16,12,tzinfo=timezone.utc)
    args={'latest':{'research_run_id':'parent','status':'imported','coverage_status':'partial',
                   'coverage_ratio':.28,'evidence_ratio':.28,'imported_at':(now-timedelta(hours=1)).isoformat()},
          'slot_attempts':1,'run_kind':'broad','now':now,
          'policy':{'maximum_continuations_per_slot':2,'cooldown_seconds':2700},
          'budget':{name:{'status':'within_budget','remaining_tokens':3500000,'remaining_uses':10}
                    for name in ['gameweek','month']}, 'job_tokens':1000000}
    args['budget']['status']='within_budget'
    args.update(changes)
    return continuation_gate(**args)


def test_partial_continues_without_erasing_original_or_accepting_evidence():
    result=gate()
    assert result['due'] is True
    assert result['continuation_of']=='parent'
    assert result['future_jobs_preserved']==2


@pytest.mark.parametrize('change,reason',[
    ({'run_kind':'final'},'final_slot_no_continuation'),
    ({'slot_attempts':3},'continuation_slot_limit'),
    ({'latest':{'status':'failed'}},'no_measured_partial_result'),
    ({'latest':{'status':'imported','coverage_status':'complete','coverage_ratio':.9,'evidence_ratio':.8}},'coverage_target_reached'),
])
def test_continuation_is_bounded(change,reason):
    result=gate(**change)
    assert result['due'] is False
    assert result['reason']==reason


def test_continuation_preserves_future_full_jobs_not_just_reservations():
    budget={name:{'status':'within_budget','remaining_tokens':2900000,'remaining_uses':10}
            for name in ['gameweek','month']}
    budget['status']='within_budget'
    assert gate(budget=budget)['reason']=='continuation_preserve_future_budget'
    assert gate(budget=budget,run_kind='refresh')['due'] is True


def test_continuation_waits_after_import_not_queue():
    latest={'research_run_id':'parent','status':'imported','coverage_status':'partial',
            'coverage_ratio':.28,'evidence_ratio':.28,'imported_at':'2026-10-16T11:40:00+00:00'}
    assert gate(latest=latest)['reason']=='continuation_cooldown'


def test_orphaned_budget_is_not_reused_for_continuation():
    budget={'status':'within_budget','orphaned_reservations':{'status':'observed'}}
    assert gate(budget=budget)['reason']=='continuation_budget_unhealthy'


def test_continuation_link_and_budget_are_atomic_and_idempotent(tmp_path):
    from test_agent_attempts import _runtime
    config,db,parent,*_= _runtime(tmp_path)
    original=db.research_run(parent)
    with db.transaction() as con:
        con.execute("UPDATE research_runs SET status='imported' WHERE research_run_id=?",(parent,))
        con.execute("UPDATE agent_budget_reservations SET status='settled',actual_tokens=100,attempt_count=1 WHERE subject_id=?",(parent,))
    payload={**original,'research_run_id':'research_'+'b'*32,'request_path':'child.json',
             'request_sha256':'b'*64,'continuation_of':parent,'continuation_future_jobs':2,
             'budget_policy':{'reservation_tokens':100,'job_tokens':120,'gw_tokens':900,
                              'month_tokens':3000,'gw_uses':20,'month_uses':60}}
    first=db.queue_research_run(payload)
    assert first['status']=='queued'
    second=db.queue_research_run({**payload,'research_run_id':'research_'+'c'*32,'request_sha256':'c'*64})
    assert second['reused'] is True
    assert second['research_run_id']==first['research_run_id']
    with db.connect(readonly=True) as con:
        assert con.execute("SELECT COUNT(*) FROM agent_budget_reservations WHERE status='reserved'").fetchone()[0]==1


def test_atomic_continuation_preserves_worst_case_inflight_jobs(tmp_path):
    from test_agent_attempts import _runtime
    config,db,parent,*_= _runtime(tmp_path)
    original=db.research_run(parent)
    with db.transaction() as con:
        con.execute("UPDATE research_runs SET status='imported' WHERE research_run_id=?",(parent,))
    payload={**original,'research_run_id':'research_'+'b'*32,'request_path':'child.json',
             'request_sha256':'b'*64,'continuation_of':parent,'continuation_future_jobs':2,
             'budget_policy':{'reservation_tokens':100,'job_tokens':120,'gw_tokens':470,
                              'month_tokens':3000,'gw_uses':20,'month_uses':60}}
    # Reservation 100 would fit 100+360, but actual allowed exposure is 120+360.
    result=db.queue_research_run(payload)
    assert result['reason']=='continuation_preserve_future_budget'
    assert db.research_run(payload['research_run_id']) is None


def test_active_campaign_continues_partial_and_carries_pending_from_ledger(tmp_path,monkeypatch):
    import json
    from test_strategic_context import _runtime
    import mova_fpl.ops.strategy as strategy
    config,db,service,cycle = _runtime(tmp_path)
    first=service.enqueue(force=True,actor='test',reason='first pass',idempotency_key='first')
    now=datetime.now(timezone.utc).replace(microsecond=0)
    old=(now-timedelta(hours=1)).isoformat()
    with db.transaction() as con:
        con.execute("UPDATE gameweek_cycles SET deadline_at=? WHERE cycle_id=?",((now+timedelta(hours=20)).isoformat(),cycle))
        con.execute("UPDATE research_runs SET status='imported',coverage_status='partial',coverage_ratio=.28,evidence_ratio=.28,queued_at=?,imported_at=?,coverage_json=? WHERE research_run_id=?",
                    (old,old,json.dumps({'subjects':[{'player_element':1,'evidence_verified':True,'status':'no_material_update'},
                                                     {'player_element':2,'evidence_verified':False,'status':'not_checked'}]}),first['research_run_id']))
        con.execute("UPDATE agent_budget_reservations SET status='settled',actual_tokens=100000,attempt_count=1 WHERE subject_id=?",(first['research_run_id'],))
    original=strategy.researcher_release
    monkeypatch.setattr(strategy,'researcher_release',lambda version=None: original(version or '1.14.0'))
    due=service.due(now=now)
    assert due['reason']=='coverage_continuation_due'
    assert due['continuation_of']==first['research_run_id']
    progress=service._research_work_progress(cycle,[{'element':1},{'element':2}],now)
    assert progress['needs_checking_elements']==[2]
    assert progress['evidence_must_be_revalidated'] is True
    second=service.enqueue()
    assert second['status']=='queued'
    assert service.due(now=now)['reason']=='previous_run_not_terminal'
    with db.connect(readonly=True) as con:
        link=con.execute("SELECT payload_json FROM audit_events WHERE event_type='research_continuation_queued'").fetchone()
    assert json.loads(link[0])['parent_run_id']==first['research_run_id']


def test_campaign_progress_keeps_work_separate_from_imported_quality(tmp_path):
    import json
    from test_strategic_context import _runtime
    config,db,service,cycle = _runtime(tmp_path)
    queued=service.enqueue(force=True,actor='test',reason='progress',idempotency_key='progress')
    logs=config.research_root/'logs';logs.mkdir(parents=True,exist_ok=True)
    run=queued['research_run_id']
    path=logs/(run+'.attempt.progress.json')
    path.write_text(json.dumps({'run_id':run,'assessed_subjects':25,'evidence_subjects':4,'reason':'source_search_exhausted'}))
    result=service.campaign_progress()
    assert result['final_acceptance'] is False
    assert result['items'][0]['progress']['assessed_subjects']==25
    assert result['items'][0]['coverage_ratio'] is None
    path.write_text(json.dumps({'run_id':'research_'+'f'*32}))
    assert service.campaign_progress()['items'][0]['progress_error']=='progress_binding_mismatch'


def test_completion_release_scales_refresh_scope_to_every_club(tmp_path):
    from test_strategic_context import _runtime
    config,db,service,cycle = _runtime(tmp_path)
    result=service.enqueue_experiment(versions=['1.18.0'],actor='test',reason='full focus',idempotency_key='campaign-scope')
    import json
    from pathlib import Path
    request=json.loads(Path(result['results'][0]['request_path']).read_text())
    clubs={row.get('team') or 'unknown:'+str(row['element']) for row in request['manifest']['research_summary']['focus']}
    assert request['scope_policy']['max_web_queries']==min(32,2*len(clubs))
    assert request['scope_policy']['max_documents']==32
