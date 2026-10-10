"""Prospective causality and anti-selection regressions for ADR-011."""
import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from mova_fpl.ops.db import sha256_json
from mova_fpl.ops.research_acceptance import current_contract, register_cohort
from test_strategic_context import _runtime


def _cohort(tmp_path, monkeypatch):
    config, db, service, cycle = _runtime(tmp_path)
    now = datetime.now(timezone.utc)
    slots = []
    for gw in (2, 3, 4):
        deadline = now + timedelta(days=gw)
        if gw == 2:
            with db.connect(readonly=True) as con:
                deadline = datetime.fromisoformat(con.execute('SELECT deadline_at FROM gameweek_cycles WHERE cycle_id=?', (cycle,)).fetchone()[0])
        slots.append({'gw': gw, 'cycle_id': f'{config.season}-gw{gw:02d}',
                      'opens_at': (now-timedelta(minutes=5)).isoformat(), 'deadline_at': deadline.isoformat()})
    manifest = {'schema': 'mova-research-acceptance-manifest-v1', 'season': config.season,
                'approval_reference': 'test-owner-approval', 'contract': current_contract(config), 'slots': slots}
    monkeypatch.setattr('mova_fpl.ops.research_acceptance.utcnow', lambda: (now-timedelta(minutes=6)).isoformat())
    registration = register_cohort(db, config, manifest, actor='owner', reason='prospective test', idempotency_key='test-cohort')
    prepared = service.prepare()
    for slot in slots[1:]:
        db.upsert_cycle(config.season, slot['gw'], slot['deadline_at'], phase='press_conferences')
        with db.transaction() as con:
            row = dict(con.execute('SELECT * FROM cycle_manifests WHERE manifest_id=?', (prepared['manifest_id'],)).fetchone())
            row.update(manifest_id=f"manifest_test{slot['gw']}", cycle_id=slot['cycle_id'], deadline_at=slot['deadline_at'], content_sha256=str(slot['gw'])*64)
            con.execute(f"INSERT INTO cycle_manifests({','.join(row)}) VALUES({','.join('?' for _ in row)})", tuple(row.values()))
    return config, db, manifest, registration, prepared


def _run(config, db, manifest, prepared, gw, *, suffix='a', experiment=False, drift=False):
    run_id = 'research_' + f'{gw:02d}' + suffix*30
    payload = {'research_run_id': run_id, 'cycle_id': f'{config.season}-gw{gw:02d}',
               'manifest_id': prepared['manifest_id'] if gw == 2 else f'manifest_test{gw}',
               'provider': config.research_provider, 'request_path': '/test/request',
               'request_sha256': sha256_json(run_id), 'budget_policy': config.agent_budget_policy(),
               'acceptance_contract': {} if drift else manifest['contract'], 'experiment': {'test': True} if experiment else None}
    db.queue_research_run(payload)
    return run_id


def _passing(db, manifest, run_id):
    now = datetime.now(timezone.utc).isoformat()
    with db.transaction() as con:
        run = con.execute('SELECT * FROM research_runs WHERE research_run_id=?', (run_id,)).fetchone()
        con.execute("UPDATE research_runs SET status='imported',result_schema='mova-research-brief-v2',coverage_status='complete',coverage_ratio=1,evidence_ratio=1,imported_at=? WHERE research_run_id=?", (now,run_id))
        con.execute("UPDATE agent_budget_reservations SET status='settled',accounting_mode='exact',actual_tokens=30,attempt_count=1,estimated_tokens=0 WHERE subject_id=?", (run_id,))
        for event, status in [('started','running'),('finished','succeeded')]:
            con.execute('''INSERT INTO agent_worker_attempt_events(event_id,attempt_id,subject_type,subject_id,request_sha256,event_type,status,model,input_tokens,output_tokens,receipt_path,receipt_sha256,occurred_at) VALUES(?,?,'research',?,?,?,?,?,10,20,'/test/receipt',?,?)''',
                        (run_id+event, run_id+'attempt', run_id, run['request_sha256'], event,status,manifest['contract']['model'],'f'*64,now))


def test_unregistered_never_inherits_historical_acceptance(tmp_path):
    config, db, _, _ = _runtime(tmp_path)
    report = db.research_acceptance(config)
    assert report['status'] == 'not_registered'
    assert report['historical'] == db.research_coverage()


def test_registration_is_immutable_and_idempotent(tmp_path, monkeypatch):
    config, db, manifest, registration, _ = _cohort(tmp_path, monkeypatch)
    assert register_cohort(db,config,manifest,actor='owner',reason='prospective test',idempotency_key='test-cohort')['reused']
    changed = {**manifest, 'approval_reference':'other'}
    with pytest.raises(ValueError, match='idempotency conflict'):
        register_cohort(db,config,changed,actor='owner',reason='prospective test',idempotency_key='test-cohort')
    with pytest.raises(sqlite3.IntegrityError, match='immutable'):
        with db.transaction() as con:
            con.execute('DELETE FROM research_acceptance_cohorts WHERE cohort_id=?',(registration['cohort_id'],))


@pytest.mark.parametrize('mutation', ['duplicate','past','drift','overlap','inferred'])
def test_invalid_cohorts_rejected(tmp_path, monkeypatch, mutation):
    config, db, manifest, _, prepared = _cohort(tmp_path, monkeypatch)
    manifest = json.loads(json.dumps(manifest))
    if mutation == 'duplicate': manifest['slots'][1]['gw']=2
    if mutation == 'past': manifest['slots'][0]['opens_at']='2020-01-01T00:00:00Z'
    if mutation == 'drift': manifest['contract']['model']='different'
    if mutation == 'inferred': _run(config,db,manifest,prepared,2)
    with pytest.raises(ValueError):
        register_cohort(db,config,manifest,actor='owner',reason='new approval',idempotency_key='second')


def test_all_predeclared_slots_required_and_historical_report_preserved(tmp_path, monkeypatch):
    config, db, manifest, _, prepared = _cohort(tmp_path,monkeypatch)
    for gw in (2,3): _passing(db,manifest,_run(config,db,manifest,prepared,gw))
    assert db.research_acceptance(config)['status']=='in_progress'
    _passing(db,manifest,_run(config,db,manifest,prepared,4))
    before=db.research_coverage()
    report=db.research_acceptance(config)
    assert report['status']=='passed'
    assert report['passing_gameweeks']==3
    assert report['historical']==before
    assert db.research_acceptance(replace(config,research_model='different'))['status']=='failed'


def test_first_failure_cannot_be_replaced_by_success_or_experiment(tmp_path,monkeypatch):
    config,db,manifest,_,prepared=_cohort(tmp_path,monkeypatch)
    _passing(db,manifest,_run(config,db,manifest,prepared,2,suffix='c',experiment=True))
    first=_run(config,db,manifest,prepared,2)
    db.reject_research_run(first,error_code='failure',error_detail='test')
    _passing(db,manifest,_run(config,db,manifest,prepared,2,suffix='b'))
    slot=db.research_acceptance(config)['active']['slots'][0]
    assert slot['research_run_id']==first
    assert slot['status']=='failed'


@pytest.mark.parametrize('problem',['coverage','evidence','usage','attempt_failure','contract'])
def test_each_quality_or_attempt_failure_blocks_acceptance(tmp_path,monkeypatch,problem):
    config,db,manifest,_,prepared=_cohort(tmp_path,monkeypatch)
    run=_run(config,db,manifest,prepared,2,drift=problem=='contract')
    _passing(db,manifest,run)
    with db.transaction() as con:
        if problem=='coverage': con.execute('UPDATE research_runs SET coverage_ratio=.89 WHERE research_run_id=?',(run,))
        if problem=='evidence': con.execute('UPDATE research_runs SET evidence_ratio=.79 WHERE research_run_id=?',(run,))
        if problem=='usage': con.execute("UPDATE agent_budget_reservations SET accounting_mode='conservative' WHERE subject_id=?",(run,))
        if problem=='attempt_failure': con.execute("UPDATE agent_worker_attempt_events SET status='failed',error_code='test' WHERE subject_id=? AND event_type='finished'",(run,))
    assert db.research_acceptance(config)['status']=='failed'


def test_worker_asset_inventory_matches_sources():
    from pathlib import Path
    import hashlib
    root=Path(__file__).resolve().parents[1]
    assets=json.loads((root/'mova_fpl/ops/research_acceptance_assets.json').read_text())
    for name,digest in assets.items():
        path=root/'deploy/research'/name
        if not path.exists(): path=root/'mova_fpl/ops'/name
        assert hashlib.sha256(path.read_bytes()).hexdigest()==digest


def test_missing_slots_fail_after_deadline(tmp_path,monkeypatch):
    config,db,_,_,_=_cohort(tmp_path,monkeypatch)
    class Later(datetime):
        @classmethod
        def now(cls,tz=None): return datetime.now(timezone.utc)+timedelta(days=10)
    monkeypatch.setattr('mova_fpl.ops.research_acceptance.datetime',Later)
    report=db.research_acceptance(config)
    assert report['status']=='failed'
    assert all(s['reasons']==['not_executed'] for s in report['active']['slots'])


def test_first_run_before_window_fails_permanently(tmp_path,monkeypatch):
    config,db,manifest,_,prepared=_cohort(tmp_path,monkeypatch)
    monkeypatch.setattr('mova_fpl.ops.db.utcnow',lambda:(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat())
    _run(config,db,manifest,prepared,2)
    report=db.research_acceptance(config)
    assert report['status']=='failed'
    assert 'run_outside_preregistered_window' in report['active']['slots'][0]['reasons']


def test_new_cohort_cannot_hide_an_already_inferred_future_gw(tmp_path,monkeypatch):
    config,db,manifest,_,prepared=_cohort(tmp_path,monkeypatch)
    cycle=db.upsert_cycle(config.season,5,(datetime.now(timezone.utc)+timedelta(days=8)).isoformat(),phase='press_conferences')
    with db.transaction() as con:
        row=dict(con.execute('SELECT * FROM cycle_manifests WHERE manifest_id=?',(prepared['manifest_id'],)).fetchone())
        row.update(manifest_id='future5',cycle_id=cycle,content_sha256='5'*64)
        con.execute(f"INSERT INTO cycle_manifests({','.join(row)}) VALUES({','.join('?' for _ in row)})",tuple(row.values()))
    db.queue_research_run({'research_run_id':'research_'+'5'*32,'cycle_id':cycle,'manifest_id':'future5','provider':config.research_provider,'request_path':'/fixture','request_sha256':'5'*64})
    manifest=json.loads(json.dumps(manifest))
    manifest['slots']=[dict(s,gw=s['gw']+3,cycle_id=f"{config.season}-gw{s['gw']+3:02d}") for s in manifest['slots']]
    manifest['slots'][0]['deadline_at']=(datetime.now(timezone.utc)+timedelta(days=8)).isoformat()
    with pytest.raises(ValueError,match='deadline disagrees|previously inferred'):
        register_cohort(db,config,manifest,actor='owner',reason='new decision',idempotency_key='different')
