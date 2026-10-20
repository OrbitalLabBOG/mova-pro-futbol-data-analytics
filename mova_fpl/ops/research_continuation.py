"""Resume uncovered subjects without changing a prior run, quota, or acceptance slot."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from mova_fpl.ops.db import sha256_json

LEGACY_POLICY = {'version': 'research-completion-v1', 'max_runs_per_slot': 3,
                 'target_coverage': 1.0, 'minimum_seconds_remaining': 600}
POLICY = {'version': 'research-completion-v2', 'target_coverage': 1.0,
          'minimum_seconds_remaining': 600, 'budget_policy': 'shared_hard_limits'}


def supported_policy(policy):
    return policy == POLICY or policy == LEGACY_POLICY


def assess(config, db, run, *, count, run_kind, seconds, new_slot=False):
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
    if not supported_policy(request.get('completion_policy')):
        return None
    if count == 0 and not new_slot:
        count = int((request.get('continuation') or {}).get('round', 1))
    coverage = json.loads(run.get('coverage_json') or '{}')
    subjects = coverage.get('subjects', [])
    from mova_fpl.ops.research_campaign import progress
    campaign = progress(config, db, run['cycle_id'])
    # Research may finish with documented uncertainty. Unknown is never an
    # accepted signal, and the next mandatory refresh revisits open questions.
    pending = campaign['pending_subjects'] if new_slot else campaign.get(
        'pending_evidence_subjects', campaign['pending_subjects'])
    if not subjects:
        return None
    if not pending:
        return {'due': False, 'reason': 'research_focus_investigated_with_uncertainty' if campaign.get('open_questions') or campaign.get('unresolved_conflicts') else 'research_focus_complete'}
    if seconds <= config.research_final_cutoff_seconds + POLICY['minimum_seconds_remaining']:
        return {'due': False, 'reason': 'completion_deadline_reserve', 'pending_subjects': pending}
    budget = db.cost_report(config.agent_budget_policy(), season=config.season,
                            gw=int(run['cycle_id'].rsplit('gw', 1)[1]))
    # No speculative reservation for future slots: queue and physical-attempt
    # admission still enforce the unchanged job/GW/month token and use limits.
    needed = config.agent_budget_policy()['job_tokens']
    if (budget['status'] != 'within_budget'
            or budget['gameweek']['remaining_tokens'] < needed
            or budget['month']['remaining_tokens'] < needed
            or budget['gameweek'].get('remaining_uses', 1) <= 0
            or budget['month'].get('remaining_uses', 1) <= 0):
        return {'due': False, 'reason': 'completion_budget_exhausted', 'pending_subjects': pending}
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
        'round': 1 if new_slot else count+1, 'pending_subjects': pending,
        'unverified_subjects': [r['player_element'] for r in campaign['subjects'] if not r['evidence_verified']],
        'unresolved_subjects': [r['player_element'] for r in campaign['subjects'] if r['evidence_verified'] and not r['resolved']],
        'prior_brief': {key: result.get(key, []) for key in ['documents', 'signals', 'conflicts']},
        'prior_verified_subjects': [int(row['player_element']) for row in subjects
                                    if row.get('evidence_verified') is True],
        'prior_evidence_is_context_only': True}}
