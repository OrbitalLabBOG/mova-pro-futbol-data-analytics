"""Read-only recovery guidance bound to existing stage clocks, never a retry engine."""
from datetime import datetime, timezone

VERSION = 'workflow-recovery-guidance-1.0.0'


def stage_guidance(stage: dict, *, now: datetime) -> dict:
    current = now.astimezone(timezone.utc)
    timing = stage.get('timing') or {}
    def passed(key):
        raw = timing.get(key)
        return bool(raw and current >= datetime.fromisoformat(raw))
    status, outcome = stage.get('status'), stage.get('outcome')
    waiting = status in {'pending', 'waiting_dependency', 'blocked', 'degraded', 'overdue'}
    if stage.get('name') == 'execute_verify' and outcome in {'ambiguous', 'failed', 'expired'}:
        action = 'reconcile_before_any_retry'
        detail = 'Read post-state and apply-once ledger; escalate ambiguity without another save.'
    elif status == 'not_due' or (status == 'skipped_policy' and outcome == 'noop'):
        action, detail = 'wait', 'Preserve cadence or audited no-action outcome.'
    elif status == 'skipped_policy':
        action, detail = 'remain_blocked', 'Preserve authority and policy blockers; do not activate writes.'
    elif waiting and (status == 'overdue' or passed('hard_stop_at')):
        action, detail = 'escalate_and_stop', 'Stage window is closed; do not execute or retry the old plan.'
    elif waiting and passed('recovery_until'):
        action, detail = 'escalate', 'Recovery margin exhausted; preserve blockers and request intervention.'
    elif status in {'blocked', 'degraded'}:
        action, detail = 'diagnose', 'Inspect canonical reason and evidence before one bounded recovery.'
    elif status == 'waiting_dependency':
        action, detail = 'wait_for_dependency', 'Observe worker/import or official data; do not duplicate the request.'
    elif status == 'pending':
        action, detail = 'complete_existing_stage', 'Use the existing entrypoint and idempotency key within its window.'
    else:
        action, detail = 'none', 'No recovery indicated by this stage snapshot.'
    return {'policy_version': VERSION, 'action': action, 'detail': detail,
            'recovery_until': timing.get('recovery_until'), 'hard_stop_at': timing.get('hard_stop_at'),
            'automatic_action': False, 'permits_execution': False}


def exception_contracts() -> list[dict]:
    """Existing guardrail responses, for inspection; no invented retries or timeouts."""
    return [
        {'condition': 'busy_lock', 'response': 'defer_to_next_scheduled_attempt',
         'constraint': 'Exit 75; no new request/key or forced lock removal.'},
        {'condition': 'auth_expired', 'response': 'block_agent_and_escalate',
         'constraint': 'Supervised reauthentication; no blind retry or copied profile.'},
        {'condition': 'stale_inputs', 'response': 'refresh_then_reseal',
         'constraint': 'New manifest/envelope/preflight; old decision cannot become executable.'},
        {'condition': 'budget_exhausted', 'response': 'defer_without_inference',
         'constraint': 'No allowance increase, duplicate reservation or fallback provider.'},
        {'condition': 'insufficient_research', 'response': 'retain_not_checked_and_block_affected_action',
         'constraint': 'No fabricated coverage, publication dates or waived quality gates.'},
        {'condition': 'invalid_or_incomplete_agent_output', 'response': 'quarantine_then_diagnose',
         'constraint': 'Preserve terminal receipt/tombstone; recovery needs new audited request, capacity and window.'},
        {'condition': 'ambiguous_save', 'response': 'read_and_reconcile',
         'constraint': 'No second save before post-state and apply-once ledger establish the result.'},
        {'condition': 'official_settlement_pending', 'response': 'wait_for_finished_and_data_checked',
         'constraint': 'No timeout can fabricate settlement or causal review.'},
    ]
