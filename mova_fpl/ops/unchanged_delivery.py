"""Durable evidence of an authenticated no-op; never evidence of a physical Save."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from mova_fpl.data.private_state import load as load_private_state
from mova_fpl.ops.collector.contracts import canonical_bytes, write_atomic

CONTRACT = 'mova-unchanged-delivery-v1'


def _sealed(config, path, expected):
    path = Path(path)
    if (not path.resolve().is_relative_to(config.artifact_root.resolve())
            or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected):
        raise RuntimeError('unchanged delivery artifact missing, external or altered')
    return json.loads(path.read_text())


def verify_state(config, db, plan, state, *, now):
    from mova_fpl.ops.execution import ExecutionService
    normalized = load_private_state(Path(state['artifact_path']), expected_team_id=config.team_id)[0]
    manifest = _sealed(config, Path(state['artifact_path'])/'manifest.json', state['manifest_sha256'])
    age = (now - datetime.fromisoformat(state['observed_at'].replace('Z', '+00:00'))).total_seconds()
    if (state['quality_status'] != 'valid' or not 0 <= age <= 300
            or normalized['event']['id'] != plan['gw']
            or manifest['quality']['fingerprint'] != state['fingerprint']
            or state['fingerprint'] != plan['action']['expected_pre_team_fingerprint']
            or ExecutionService._observed_decision_fingerprint(plan, normalized)
            != plan['action']['expected_post_decision_fingerprint']):
        raise RuntimeError('unchanged delivery requires a fresh exact authenticated state')
    return normalized


def seal_receipt(config, db, plan, *, now, proof):
    with db.connect(readonly=True) as con:
        row = con.execute('SELECT * FROM team_state_snapshots WHERE cycle_id=? '
                          'ORDER BY observed_at DESC LIMIT 1', (plan['cycle_id'],)).fetchone()
    if not row:
        raise RuntimeError('unchanged delivery missing private state')
    state = dict(row)
    verify_state(config, db, plan, state, now=now)
    body = {'schema': CONTRACT, 'cycle_id': plan['cycle_id'], 'plan_id': plan['plan_id'],
            'plan_sha256': plan['content_sha256'], 'envelope': plan['envelope'],
            'observed_at': now.isoformat(), 'team_state_id': state['team_state_id'],
            'private_state_fingerprint': state['fingerprint'],
            'decision_fingerprint': plan['action']['expected_post_decision_fingerprint'],
            'delivery_proof': proof, 'physical_save': False,
            **({'delivery_stage': plan['delivery_stage']} if plan.get('delivery_stage') else {}),
            'verification_checks': plan['authorization']['checks']}
    payload = canonical_bytes(body)
    digest = hashlib.sha256(payload).hexdigest()
    path = config.artifact_root/'delivery-receipts'/plan['cycle_id']/(digest+'.json')
    write_atomic(path, payload)
    return {'receipt_contract': CONTRACT, 'evidence_path': str(path), 'evidence_sha256': digest}


def closeout_source(config, db, cycle_id):
    """Load a regular receipt through its immutable plan; legacy/proof jobs cannot qualify."""
    from mova_fpl.ops.execution import ExecutionService
    job = db.delivery_receipt(cycle_id)
    if not job:
        return None
    metrics = json.loads(job['metrics_json'])
    if metrics.get('receipt_contract') != CONTRACT:
        return None
    receipt = _sealed(config, metrics['evidence_path'], metrics['evidence_sha256'])
    source = db.execution_claim_source(metrics['plan_id'])
    plan = ExecutionService(config, db)._load_plan(source['plan'])
    controls = plan['controls']
    if (receipt['schema'] != CONTRACT or receipt['cycle_id'] != cycle_id
            or receipt['delivery_proof'] is not False or plan.get('delivery_proof')
            or receipt.get('delivery_stage') == 'provisional' or plan.get('delivery_stage') == 'provisional'
            or receipt.get('delivery_stage') != plan.get('delivery_stage')
            or receipt['physical_save'] is not False or plan['action']['risk_class'] != 'R0'
            or plan['authorization']['status'] != 'noop'
            or not all(c['passed'] for c in plan['authorization']['checks'])
            or receipt['verification_checks'] != plan['authorization']['checks']
            or receipt['plan_sha256'] != plan['content_sha256']
            or receipt['envelope'] != plan['envelope']
            or controls.get('delivery_scope') != 'lineup-v1'
            or controls.get('action_level') != 'A2' or controls.get('mode') != 'autonomous'
            or controls.get('browser_writes') is not True or controls.get('kill_switch') is not False
            or controls.get('compliance_gate') != 'approved'):
        raise RuntimeError('unchanged delivery receipt does not reproduce its authorized plan')
    observed = datetime.fromisoformat(receipt['observed_at'].replace('Z', '+00:00'))
    deadline = datetime.fromisoformat(plan['deadline_at'].replace('Z', '+00:00'))
    if not 1800 < (deadline-observed).total_seconds() <= 10800:
        raise RuntimeError('unchanged delivery receipt outside regular window')
    with db.connect(readonly=True) as con:
        row = con.execute('SELECT * FROM team_state_snapshots WHERE team_state_id=? AND cycle_id=?',
                          (receipt['team_state_id'], cycle_id)).fetchone()
        decision = con.execute('SELECT * FROM decision_runs WHERE decision_id=?',
                               (plan['envelope']['decision_id'],)).fetchone()
    if not row or not decision:
        raise RuntimeError('unchanged delivery receipt missing durable sources')
    state = dict(row)
    verify_state(config, db, plan, state, now=observed)
    if (receipt['private_state_fingerprint'] != state['fingerprint']
            or receipt['decision_fingerprint'] != decision['fingerprint']):
        raise RuntimeError('unchanged delivery fingerprint mismatch')
    return {**dict(decision), 'execution_id': job['job_id'], 'action_level': 'A2',
            'envelope_sha256': plan['envelope']['content_sha256'],
            'started_at': state['observed_at'], 'finished_at': state['observed_at'],
            'evidence_path': metrics['evidence_path'], 'evidence_sha256': metrics['evidence_sha256'],
            'observed_post_fingerprint': receipt['decision_fingerprint'],
            'receipt_envelope_id': plan['envelope']['envelope_id'],
            'receipt_candidate_key': plan['envelope']['selected_candidate_key'],
            'receipt_team_state_id': state['team_state_id']}
