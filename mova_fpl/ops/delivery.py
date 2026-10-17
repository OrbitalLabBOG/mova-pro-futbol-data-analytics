"""Bounded host dispatch: scheduling is independent of public collection cadence."""
from __future__ import annotations

from datetime import datetime, timezone

from mova_fpl.ops.execution import ExecutionService

LINEUP_SCOPE = "lineup-v1"


class DeliveryService:
    def __init__(self, config, db):
        self.config, self.db = config, db

    def dispatch(self, *, actor: str, reason: str, check_only: bool = False,
                 now: datetime | None = None) -> dict:
        if not actor.strip() or not reason.strip():
            raise ValueError("delivery requires actor and reason")
        current = now or datetime.now(timezone.utc)
        controls = {k: v['value'] for k, v in self.db.controls().items()}
        cycle = self.db.status().get('cycle') or {}
        result = {'schema': 'mova-delivery-dispatch-v1', 'cycle_id': cycle.get('cycle_id'),
                  'scope': controls.get('delivery_scope'), 'status': 'blocked'}
        if controls.get('delivery_scope') != LINEUP_SCOPE:
            return {**result, 'reason': 'delivery_scope_disabled'}
        if not (controls.get('mode') == 'autonomous' and controls.get('action_level') == 'A2'
                and controls.get('browser_writes') is True and controls.get('kill_switch') is False
                and controls.get('compliance_gate') == 'approved'):
            return {**result, 'reason': 'authority_not_enabled'}
        if not cycle.get('deadline_at'):
            return {**result, 'reason': 'cycle_missing'}
        seconds = (datetime.fromisoformat(cycle['deadline_at'].replace('Z', '+00:00')) - current).total_seconds()
        if not 30 * 60 < seconds <= 3 * 3600:
            return {**result, 'status': 'not_due', 'reason': 'outside_delivery_window'}
        previous = self.db.latest_delivery_attempt(cycle['cycle_id'])
        if previous and previous['status'] in {'verified', 'applying', 'ambiguous', 'claimed'}:
            return {**result, 'status': previous['status'], 'execution_id': previous['execution_id'],
                    'reason': 'existing_attempt_no_duplicate'}
        if check_only:
            return {**result, 'status': 'due', 'refresh_key':
                    f"delivery-refresh:{cycle['cycle_id']}:{int(current.timestamp()) // 300}"}
        service = ExecutionService(self.config, self.db)
        if previous and previous['status'] == 'prepared':
            # Claim revalidates all mutable gates; never dispatch a second prepared attempt.
            return {**result, 'status': 'prepared', 'execution_id': previous['execution_id']}
        plan = service.preflight(actor=actor, reason=reason, now=current,
                                 idempotency_key=f"delivery-preflight:{cycle['cycle_id']}:{int(current.timestamp()) // 300}")
        row = self.db.execution_claim_source(plan['plan_id'])['plan']
        loaded = service._load_plan(row)
        if loaded['action']['risk_class'] not in {'R0', 'R2'}:
            return {**result, 'reason': 'scope_requires_lineup_only'}
        if loaded['authorization']['status'] == 'noop':
            # A no-op still requires a fresh private state and all data/authority gates.
            failed = [c['code'] for c in loaded['authorization']['checks'] if not c['passed']]
            if failed:
                return {**result, 'reason': 'noop_checks_failed', 'blocking_codes': failed}
            job, reused = self.db.start_job('delivery', f"delivery-noop:{cycle['cycle_id']}:{row['expected_pre_fingerprint']}",
                                            'corr_delivery', cycle_id=cycle['cycle_id'])
            if not reused:
                self.db.finish_job(job, 'completed', metrics={'status': 'unchanged_verified', 'plan_id': plan['plan_id']})
            return {**result, 'status': 'unchanged_verified', 'job_id': job}
        if row['status'] != 'authorized':
            return {**result, 'reason': 'preflight_blocked',
                    'blocking_codes': loaded['authorization']['blocking_codes']}
        prepared = service.prepare(plan_id=plan['plan_id'], adapter='browser', actor=actor, reason=reason,
                                   idempotency_key=f"delivery:{plan['plan_id']}", now=current)
        return {**result, 'status': prepared['status'], 'execution_id': prepared['execution_id']}
