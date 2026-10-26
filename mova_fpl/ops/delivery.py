"""Bounded host dispatch: scheduling is independent of public collection cadence."""
from __future__ import annotations

from datetime import datetime, timezone

from mova_fpl.ops.execution import ExecutionService
from mova_fpl.ops.delivery_policy import lineup_proof
from mova_fpl.ops.unchanged_delivery import seal_receipt
from mova_fpl.ops.progressive_delivery import enabled, stage, cadence

LINEUP_SCOPE = "lineup-v1"


class DeliveryService:
    def __init__(self, config, db):
        self.config, self.db = config, db

    def dispatch(self, *, actor: str, reason: str, check_only: bool = False,
                 now: datetime | None = None, proof: bool = False) -> dict:
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
        from mova_fpl.ops.manual_delivery import hold
        manual = hold(self.db, cycle.get('cycle_id'))
        if manual:
            return {**result, 'reason': 'manual_cycle_hold',
                    'execution_id': manual['execution_id']}
        seconds = (datetime.fromisoformat(cycle['deadline_at'].replace('Z', '+00:00')) - current).total_seconds()
        proof_allowed = proof and lineup_proof(controls, cycle['cycle_id'], current)
        if not proof and lineup_proof(controls, cycle['cycle_id'], current):
            return {**result, 'status': 'not_due', 'reason': 'expiring_live_proof_in_progress'}
        if proof and not proof_allowed:
            return {**result, 'reason': 'live_proof_not_approved_or_expired'}
        progressive = enabled(controls) and not proof
        weekly_stage = stage(controls, cycle['deadline_at'], current) if progressive else None
        if not (seconds > 30*60 and (seconds <= 3*3600 or proof_allowed or weekly_stage)):
            return {**result, 'status': 'not_due', 'reason': 'outside_delivery_window'}
        previous = self.db.latest_delivery_attempt(cycle['cycle_id'])
        if previous and previous['status'] == 'verified':
            previous_plan = ExecutionService(self.config, self.db)._load_plan(
                self.db.execution_claim_source(previous['plan_id'])['plan'])
            if previous_plan.get('delivery_proof') and (not proof or previous_plan.get('controls', {}).get('delivery_proof') != controls.get('delivery_proof')):
                previous = None
        if progressive and previous and previous['status'] == 'verified':
            previous = None
        if previous and previous['status'] in {'verified', 'applying', 'ambiguous', 'claimed'}:
            return {**result, 'status': previous['status'], 'execution_id': previous['execution_id'],
                    'reason': 'existing_attempt_no_duplicate'}
        last = self.db.latest_delivery_verification(cycle['cycle_id']) if progressive else None
        if last and last['stage'] == weekly_stage and (not previous or previous['status'] != 'prepared'):
            age = (current - datetime.fromisoformat(last['observed_at'].replace('Z', '+00:00'))).total_seconds()
            if 0 <= age < cadence(seconds):
                return {**result, 'status': 'not_due', 'reason': 'delivery_review_cadence', 'latest_verification': last}
        if check_only:
            return {**result, 'status': 'due', 'refresh_key':
                    f"delivery-refresh:{cycle['cycle_id']}:{weekly_stage or ('proof' if proof else 'final')}:{int(current.timestamp()) // 300}"}
        service = ExecutionService(self.config, self.db)
        if previous and previous['status'] == 'prepared':
            # Claim revalidates all mutable gates; never dispatch a second prepared attempt.
            return {**result, 'status': 'prepared', 'execution_id': previous['execution_id']}
        plan = service.preflight(actor=actor, reason=reason, now=current,
                                 idempotency_key=f"delivery-preflight:{cycle['cycle_id']}:{weekly_stage or ('proof' if proof else 'final')}:{int(current.timestamp()) // 300}")
        row = self.db.execution_claim_source(plan['plan_id'])['plan']
        loaded = service._load_plan(row)
        if loaded['action']['risk_class'] not in {'R0', 'R2'}:
            return {**result, 'reason': 'scope_requires_lineup_only'}
        if loaded['authorization']['status'] == 'noop':
            # A no-op still requires a fresh private state and all data/authority gates.
            failed = [c['code'] for c in loaded['authorization']['checks'] if not c['passed']]
            if failed:
                return {**result, 'reason': 'noop_checks_failed', 'blocking_codes': failed}
            receipt = seal_receipt(self.config, self.db, loaded, now=current, proof=proof)
            noop_key = (f"delivery-noop:{cycle['cycle_id']}:{weekly_stage}:{plan['plan_id']}" if progressive else
                        f"delivery-noop:{cycle['cycle_id']}:{'proof' if proof else 'final'}:{row['expected_pre_fingerprint']}")
            job, reused = self.db.start_job('delivery', noop_key, 'corr_delivery', cycle_id=cycle['cycle_id'])
            if reused:
                existing = self.db.get_job_by_key(noop_key)
                if not existing or existing['status'] != 'completed':
                    return {**result, 'reason': 'previous_noop_job_not_completed', 'job_id': job}
            if not reused:
                self.db.finish_job(job, 'completed', output_sha256=receipt['evidence_sha256'],
                                   metrics={'status': 'unchanged_verified', 'plan_id': plan['plan_id'],
                                            'delivery_proof': proof,
                                            **({'delivery_stage': weekly_stage, 'delivery_observed_at': current.isoformat()} if progressive else {}), **receipt})
            return {**result, 'status': 'unchanged_verified', 'job_id': job}
        if row['status'] != 'authorized':
            return {**result, 'reason': 'preflight_blocked',
                    'blocking_codes': loaded['authorization']['blocking_codes']}
        prepared = service.prepare(plan_id=plan['plan_id'], adapter='browser', actor=actor, reason=reason,
                                   idempotency_key=f"delivery:{plan['plan_id']}", now=current)
        return {**result, 'status': prepared['status'], 'execution_id': prepared['execution_id']}
