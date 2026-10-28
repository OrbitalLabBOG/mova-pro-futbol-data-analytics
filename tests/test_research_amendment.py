"""Explicit prospective exception preserves original registration and quality policy."""
import copy
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from mova_fpl.ops.db import sha256_json
from mova_fpl.ops.research_acceptance import current_contract, register_cohort
from mova_fpl.ops.research_amendment import amend_cohort
from test_strategic_context import _runtime


def setup_amendment(tmp_path, monkeypatch):
    config, db, service, cycle = _runtime(tmp_path)
    new = current_contract(config, campaign=True)
    old = copy.deepcopy(new)
    old['agent_version'] = '1.17.0'
    old['release'].pop('budget_close_fraction')
    old['worker_assets']['codex-app-server.mjs'] = 'a'*64
    now = datetime.now(timezone.utc)
    manifest = {'schema':'mova-research-acceptance-manifest-v2', 'season':config.season,
        'approval_reference':'original-approval', 'contract':old, 'slots':[
            {'gw':gw, 'cycle_id':f'{config.season}-gw{gw:02d}',
             'opens_at':(now+timedelta(days=gw)).isoformat(),
             'deadline_at':(now+timedelta(days=gw+3)).isoformat()} for gw in (10,11,12)]}
    with monkeypatch.context() as m:
        m.setattr('mova_fpl.ops.research_acceptance.current_contract', lambda *a,**k:old)
        registration = register_cohort(db,config,manifest,actor='owner',reason='original',idempotency_key='original')
    prepared = service.prepare()
    run_id = 'research_'+'1'*32
    request = {'research_run_id':run_id, 'cycle_id':cycle, 'experiment':{'operational_import':False},
               'acceptance_contract':new}
    request['request_sha256'] = sha256_json(request)
    config.research_root.mkdir(parents=True,exist_ok=True)
    path = config.research_root/'experiment.request.json'
    path.write_text(json.dumps(request))
    db.queue_research_run({'research_run_id':run_id,'cycle_id':cycle,
        'manifest_id':prepared['manifest_id'], 'provider':config.research_provider,
        'budget_policy':config.agent_budget_policy(), 'request_path':str(path),'request_sha256':request['request_sha256'], 'experiment':request['experiment']})
    with db.transaction() as con:
        con.execute("UPDATE research_runs SET status='completed' WHERE research_run_id=?", (run_id,))
        con.execute("UPDATE agent_budget_reservations SET status='settled',accounting_mode='exact',actual_tokens=50 WHERE subject_id=?",(run_id,))
        for event,status in [('started','running'),('finished','succeeded')]:
            con.execute('''INSERT INTO agent_worker_attempt_events(event_id,attempt_id,subject_type,subject_id,request_sha256,event_type,status,model,input_tokens,output_tokens,receipt_path,receipt_sha256,occurred_at) VALUES(?,?,'research',?,?,?,?,?,40,10,'/test/receipt',?,?)''',
                (run_id+event,run_id+'attempt',run_id,request['request_sha256'],event,status,new['model'],'f'*64,now.isoformat()))
    amendment = {'schema':'mova-research-budget-amendment-v1',
        'cohort_id':registration['cohort_id'],'original_manifest_sha256':registration['manifest_sha256'],
        'contract':new,'approval_reference':'explicit-human-exception', 'validation_run_id':run_id}
    return config,db,manifest,amendment


def apply(config,db,request,**kw):
    return amend_cohort(db,config,request,actor='owner',reason='budget pacing approved',idempotency_key=kw.get('key','amend'))


def test_amendment_preserves_original_and_selects_new_contract(tmp_path,monkeypatch):
    config,db,original,request=setup_amendment(tmp_path,monkeypatch)
    assert db.research_acceptance(config)['active']['status']=='failed'  # drift before explicit amendment
    result=apply(config,db,request)
    assert not result['reused']
    assert apply(config,db,request)['reused']
    with db.connect(readonly=True) as con:
        row=con.execute('SELECT * FROM research_acceptance_cohorts').fetchone()
        assert json.loads(row['manifest_json'])==original
        assert row['manifest_sha256']==request['original_manifest_sha256']
    active=db.research_acceptance(config)['active']
    assert active['status']=='in_progress'
    assert active['manifest_sha256']==request['original_manifest_sha256']
    assert active['amendment']['manifest_sha256']==result['manifest_sha256']
    assert all(s['status']=='pending' and not s['reasons'] for s in active['slots'])
    for operation in ['UPDATE research_acceptance_amendments SET actor=\'other\'', 'DELETE FROM research_acceptance_amendments']:
        with pytest.raises(sqlite3.IntegrityError,match='immutable'):
            with db.transaction() as con: con.execute(operation)


@pytest.mark.parametrize('problem',['budget','criteria','model','release','approval','hash','validation','failed_attempt','unknown_usage','window','inferred'])
def test_amendment_rejects_scope_or_causality_changes(tmp_path,monkeypatch,problem):
    config,db,original,request=setup_amendment(tmp_path,monkeypatch)
    if problem=='budget': request['contract']['budget']['gw_tokens']+=1
    if problem=='criteria': request['contract']['policy']['minimum_coverage_ratio']=.8
    if problem=='model': request['contract']['model']='other'
    if problem=='release': request['contract']['release']['logical_token_guard']+=1
    if problem=='approval': request['approval_reference']=''
    if problem=='hash': request['original_manifest_sha256']='0'*64
    if problem=='validation': request['validation_run_id']='missing'
    if problem=='window':
        monkeypatch.setattr('mova_fpl.ops.research_amendment.utcnow',lambda:original['slots'][0]['opens_at'])
    with db.transaction() as con:
        if problem=='failed_attempt': con.execute("UPDATE agent_worker_attempt_events SET status='failed',error_code='test' WHERE event_type='finished'")
        if problem=='unknown_usage': con.execute("UPDATE agent_budget_reservations SET accounting_mode='conservative'")
        if problem=='inferred':
            # Existing experiment on a target cycle also disqualifies amendment.
            slot=original['slots'][0]
            con.execute('INSERT INTO gameweek_cycles(cycle_id,season,gw,deadline_at,phase,status,first_observed_at,last_observed_at) SELECT ?,season,?,deadline_at,phase,status,first_observed_at,last_observed_at FROM gameweek_cycles LIMIT 1', (slot['cycle_id'],slot['gw']))
            con.execute('UPDATE research_runs SET cycle_id=?',(slot['cycle_id'],))
    with pytest.raises(ValueError): apply(config,db,request)
    with db.connect(readonly=True) as con:
        assert con.execute('SELECT COUNT(*) FROM research_acceptance_amendments').fetchone()[0]==0


def test_no_second_revision_and_replay_conflicts(tmp_path,monkeypatch):
    config,db,_,request=setup_amendment(tmp_path,monkeypatch)
    apply(config,db,request)
    with pytest.raises(ValueError,match='already amended'): apply(config,db,request,key='second')
    request['approval_reference']='changed'
    with pytest.raises(ValueError,match='idempotency conflict'): apply(config,db,request)
