"""Bounded continuation policy; never merges evidence or grants acceptance."""
from __future__ import annotations

from datetime import datetime


def continuation_gate(*, latest: dict, slot_attempts: int, run_kind: str,
                      now: datetime, policy: dict, budget: dict, job_tokens: int) -> dict:
    if budget.get('status') != 'within_budget' or budget.get('orphaned_reservations', {}).get('status', 'none') != 'none':
        return {'due': False, 'reason': 'continuation_budget_unhealthy'}
    if run_kind == 'final':
        return {'due': False, 'reason': 'final_slot_no_continuation'}
    if latest.get('status') != 'imported' or latest.get('coverage_status') not in {'partial', 'failed', 'complete'}:
        return {'due': False, 'reason': 'no_measured_partial_result'}
    if latest.get('coverage_ratio') is None or latest.get('evidence_ratio') is None:
        return {'due': False, 'reason': 'no_measured_partial_result'}
    if float(latest['coverage_ratio']) >= .9 and float(latest['evidence_ratio']) >= .8:
        return {'due': False, 'reason': 'coverage_target_reached'}
    if slot_attempts >= 1 + policy['maximum_continuations_per_slot']:
        return {'due': False, 'reason': 'continuation_slot_limit'}
    imported = datetime.fromisoformat(str(latest['imported_at']).replace('Z', '+00:00'))
    if imported.tzinfo is None:
        return {'due': False, 'reason': 'invalid_import_timestamp'}
    if (now - imported).total_seconds() < policy['cooldown_seconds']:
        return {'due': False, 'reason': 'continuation_cooldown'}
    future_jobs = 2 if run_kind == 'broad' else 1
    needed_jobs = 1 + future_jobs
    for name in ('gameweek', 'month'):
        scope = budget.get(name) or {}
        if (scope.get('status') != 'within_budget'
                or int(scope.get('remaining_tokens', 0)) < needed_jobs * job_tokens
                or int(scope.get('remaining_uses', 0)) < needed_jobs):
            return {'due': False, 'reason': 'continuation_preserve_future_budget'}
    return {'due': True, 'reason': 'coverage_continuation_due',
            'continuation_of': latest['research_run_id'],
            'future_jobs_preserved': future_jobs}
