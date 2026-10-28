"""Owner-approved, single prospective budget-pacing amendment; originals stay immutable."""
from __future__ import annotations

import hashlib
import json

from mova_fpl.ops.db import canonical_json, sha256_json, utcnow
from mova_fpl.ops.research_acceptance import _time, current_contract


def effective_manifest(con, row):
    amendment = con.execute('SELECT * FROM research_acceptance_amendments WHERE cohort_id=?',
                           (row['cohort_id'],)).fetchone()
    if not amendment:
        return json.loads(row['manifest_json']), None
    manifest = json.loads(amendment['manifest_json'])
    request = json.loads(amendment['request_json'])
    if (sha256_json(manifest) != amendment['manifest_sha256']
            or sha256_json(request) != amendment['request_sha256']
            or request['original_manifest_sha256'] != row['manifest_sha256']):
        raise ValueError('acceptance amendment integrity failure')
    return manifest, {k: amendment[k] for k in
        ('amendment_id', 'manifest_sha256', 'registered_at', 'actor', 'reason')} | {
        'original_manifest_sha256': row['manifest_sha256'],
        'approval_reference': request['approval_reference'],
        'validation_run_id': request['validation_run_id']}


def _validate_experiment(con, config, run_id, contract, target_cycles):
    from mova_fpl.ops.research_campaign_acceptance import _sealed_request
    run = con.execute('SELECT * FROM research_runs WHERE research_run_id=?', (run_id,)).fetchone()
    if not run or run['status'] != 'completed' or run['cycle_id'] in target_cycles:
        raise ValueError('amendment requires completed independent experiment')
    request = _sealed_request(config, dict(run))
    execution_keys = ('agent_version', 'release', 'provider', 'model', 'reasoning_effort',
                      'worker_assets', 'budget')
    if (not request.get('experiment') or any(
            (request.get('acceptance_contract') or {}).get(k) != contract[k] for k in execution_keys)):
        raise ValueError('validation experiment contract mismatch')
    observed_implementation = (request.get('acceptance_contract') or {}).get('implementation', {})
    execution_sources = {k:v for k,v in contract['implementation'].items()
                         if k != 'research_campaign_acceptance.py'}
    if any(observed_implementation.get(k) != v for k,v in execution_sources.items()):
        raise ValueError('validation experiment implementation mismatch')
    reservation = con.execute('SELECT * FROM agent_budget_reservations WHERE subject_id=?', (run_id,)).fetchone()
    events = con.execute("SELECT * FROM agent_worker_attempt_events WHERE subject_type='research' AND subject_id=?", (run_id,)).fetchall()
    starts = {e['attempt_id'] for e in events if e['event_type'] == 'started'}
    ends = [e for e in events if e['event_type'] == 'finished']
    if (not starts or starts != {e['attempt_id'] for e in ends}
            or any(e['status'] != 'succeeded' or e['input_tokens'] is None or e['output_tokens'] is None for e in ends)
            or not reservation or reservation['status'] != 'settled'
            or reservation['accounting_mode'] != 'exact' or reservation['actual_tokens'] is None
            or reservation['actual_tokens'] > contract['release']['logical_token_guard']):
        raise ValueError('validation experiment usage or attempts unproven')


def amend_cohort(db, config, request, *, actor, reason, idempotency_key):
    if not all(isinstance(v, str) and v.strip() for v in (actor, reason, idempotency_key)):
        raise ValueError('amendment requires actor, reason and idempotency_key')
    if (set(request) != {'schema', 'cohort_id', 'original_manifest_sha256', 'contract',
                        'approval_reference', 'validation_run_id'}
            or request['schema'] != 'mova-research-budget-amendment-v1'
            or not isinstance(request['approval_reference'], str) or not request['approval_reference'].strip()):
        raise ValueError('invalid budget amendment request')
    digest, now = sha256_json(request), utcnow()
    with db.transaction() as con:
        existing = con.execute('SELECT * FROM research_acceptance_amendments WHERE idempotency_key=?', (idempotency_key,)).fetchone()
        if existing:
            if existing['request_sha256'] != digest or existing['actor'] != actor or existing['reason'] != reason:
                raise ValueError('amendment idempotency conflict')
            return {'amendment_id': existing['amendment_id'], 'manifest_sha256': existing['manifest_sha256'], 'reused': True}
        row = con.execute('SELECT * FROM research_acceptance_cohorts WHERE cohort_id=?', (request['cohort_id'],)).fetchone()
        if not row or row['manifest_sha256'] != request['original_manifest_sha256']:
            raise ValueError('original cohort or hash mismatch')
        if con.execute('SELECT 1 FROM research_acceptance_amendments WHERE cohort_id=?', (row['cohort_id'],)).fetchone():
            raise ValueError('cohort already amended')
        original = json.loads(row['manifest_json'])
        if original['schema'] != 'mova-research-acceptance-manifest-v2':
            raise ValueError('amendment requires campaign v2')
        old, new = original['contract'], request['contract']
        if new != current_contract(config, campaign=True):
            raise ValueError('amendment contract drift')
        # Only this approved budget-pacing change; no general permission to alter policy.
        allowed = {'implementation', 'worker_assets', 'agent_version', 'release'}
        if ({k:v for k,v in old.items() if k not in allowed} != {k:v for k,v in new.items() if k not in allowed}
                or old['agent_version'] != '1.17.0' or new['agent_version'] != '1.18.0'
                or new['release'] != {**old['release'], 'budget_close_fraction': 0.5}):
            raise ValueError('amendment may only change budget pacing implementation')
        cycles = {s['cycle_id'] for s in original['slots']}
        for slot in original['slots']:
            if _time(now) >= _time(slot['opens_at']):
                raise ValueError('amendment window already opened')
            if con.execute('SELECT 1 FROM research_runs WHERE cycle_id=?', (slot['cycle_id'],)).fetchone():
                raise ValueError('amendment forbidden after any research run, including experiments')
            if con.execute('SELECT 1 FROM research_acceptance_slots WHERE cohort_id=? AND cycle_id=?',
                           (row['cohort_id'], slot['cycle_id'])).fetchone():
                raise ValueError('amendment forbidden after slot binding')
        _validate_experiment(con, config, request['validation_run_id'], new, cycles)
        manifest = {**original, 'contract': new}
        amended_hash = sha256_json(manifest)
        amendment_id = 'amendment_' + hashlib.sha256(idempotency_key.encode()).hexdigest()[:32]
        con.execute('INSERT INTO research_acceptance_amendments VALUES(?,?,?,?,?,?,?,?,?,?)',
            (amendment_id, row['cohort_id'], idempotency_key, canonical_json(request), digest,
             canonical_json(manifest), amended_hash, now, actor, reason))
        db.append_audit('research_acceptance_amended', actor=actor, subject_type='research_acceptance',
            subject_id=row['cohort_id'], payload={'amendment_id':amendment_id,
                'original_manifest_sha256':row['manifest_sha256'], 'manifest_sha256':amended_hash,
                'approval_reference':request['approval_reference'], 'validation_run_id':request['validation_run_id'],
                'idempotency_key':idempotency_key, 'reason':reason}, con=con)
    return {'cohort_id':request['cohort_id'], 'amendment_id':amendment_id,
            'original_manifest_sha256':request['original_manifest_sha256'],
            'manifest_sha256':amended_hash, 'registered_at':now, 'reused':False}
