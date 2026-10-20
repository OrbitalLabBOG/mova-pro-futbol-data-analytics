"""Resume uncovered subjects without changing a prior run, quota, or acceptance slot."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from mova_fpl.ops.db import sha256_json

POLICY = {'version': 'research-completion-v1', 'max_runs_per_slot': 3,
          'target_coverage': 1.0, 'minimum_seconds_remaining': 600}


def assess(config, db, run, *, count, run_kind, seconds):
    if run['status'] != 'imported':
        return None
    request_path = Path(run['request_path'])
    if not request_path.is_file():
        request_path = config.research_root/'archive'/request_path.name
    if not request_path.is_file():
        return None
    try:
        if (not request_path.resolve().is_relative_to(config.research_root.resolve())
                or request_path.stat().st_size > 1_048_576):
            raise ValueError('invalid parent request path or size')
        request = json.loads(request_path.read_text())
        unsigned = {key: value for key, value in request.items() if key != 'request_sha256'}
        if request.get('request_sha256') != run['request_sha256'] or sha256_json(unsigned) != run['request_sha256']:
            raise ValueError('parent request hash mismatch')
    except (OSError, ValueError, TypeError):
        return {'due': False, 'reason': 'completion_parent_request_invalid'}
    if request.get('completion_policy') != POLICY:
        return None
    if count == 0:
        count = int((request.get('continuation') or {}).get('round', 1))
    coverage = json.loads(run.get('coverage_json') or '{}')
    subjects = coverage.get('subjects', [])
    pending = [int(row['player_element']) for row in subjects
               if row.get('evidence_verified') is not True or row.get('status') == 'unresolved']
    if not subjects:
        return None
    if not pending:
        return {'due': False, 'reason': 'research_focus_complete'}
    if count >= POLICY['max_runs_per_slot']:
        return {'due': False, 'reason': 'completion_slot_limit', 'pending_subjects': pending}
    if seconds <= config.research_final_cutoff_seconds + POLICY['minimum_seconds_remaining']:
        return {'due': False, 'reason': 'completion_deadline_reserve', 'pending_subjects': pending}
    budget = db.cost_report(config.agent_budget_policy(), season=config.season,
                            gw=int(run['cycle_id'].rsplit('gw', 1)[1]))
    # Reserve the full job ceiling for future refresh/final slots; existing per-job,
    # GW/month authorizations remain mandatory in queue/attempt transactions.
    future_slots = {'broad': 2, 'refresh': 1, 'final': 0}[run_kind]
    needed = config.agent_budget_policy()['job_tokens'] * (future_slots+1)
    if (budget['status'] != 'within_budget'
            or budget['gameweek']['remaining_tokens'] < needed
            or budget['month']['remaining_tokens'] < needed):
        return {'due': False, 'reason': 'completion_budget_reserved', 'pending_subjects': pending}
    result_path = Path(run['result_path'])
    if (not result_path.resolve().is_relative_to(config.research_root.resolve())
            or not result_path.is_file()
            or hashlib.sha256(result_path.read_bytes()).hexdigest() != run['result_sha256']):
        return {'due': False, 'reason': 'completion_parent_artifact_invalid'}
    result = json.loads(result_path.read_text())
    # These are discovery hints only. Every document/coverage row in a new result
    # goes through the normal independent fetch and importer again.
    return {'due': True, 'reason': 'completion_pending', 'continuation': {
        'parent_run_id': run['research_run_id'], 'parent_result_sha256': run['result_sha256'],
        'round': count+1, 'pending_subjects': pending,
        'prior_brief': {key: result.get(key, []) for key in ['documents', 'signals', 'conflicts', 'coverage']},
        'prior_evidence_is_context_only': True}}
