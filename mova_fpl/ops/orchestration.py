"""Lectura y rehearsal hermético del grafo de orquestación MOVA.

El reporte no agenda trabajo ni concede autoridad. Traduce el ledger vigente a
una secuencia pequeña y verificable para que un operador pueda distinguir entre
trabajo completado, espera temporal, degradación de un agente y una violación de
dependencias.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB, sha256_json

SCHEMA = "mova-orchestration-status-v1"
DRILL_SCHEMA = "mova-orchestration-drill-v1"
TERMINAL_DELIBERATIONS = {"accepted", "review_required", "blocked"}
TERMINAL_BAD = {"failed", "rejected", "ambiguous", "expired"}


def _stage(name: str, owner: str, status: str, *, outcome: str | None = None,
           subject_id: str | None = None, next_action: str | None = None) -> dict:
    return {
        "name": name,
        "owner": owner,
        "status": status,
        "outcome": outcome,
        "subject_id": subject_id,
        "next_action": next_action if status in {"pending", "blocked", "degraded"} else None,
    }


def evaluate_workflow(observed: dict, *, now: datetime | None = None) -> dict:
    """Evalúa observaciones ya recolectadas; no realiza IO ni mutaciones."""
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cycle = observed.get("cycle") or {}
    deadline_raw = cycle.get("deadline_at")
    deadline = (
        datetime.fromisoformat(str(deadline_raw).replace("Z", "+00:00"))
        if deadline_raw else None
    )
    source = observed.get("source") or {}
    team = observed.get("team_state") or {}
    manifest = observed.get("manifest") or {}
    research = observed.get("research") or {}
    envelope = observed.get("envelope") or {}
    deliberation = observed.get("deliberation") or {}
    plan = observed.get("preflight") or {}
    attempt = observed.get("execution") or {}
    settlement = observed.get("settlement") or {}
    review = observed.get("review") or {}
    learning = observed.get("learning") or {}

    stages: list[dict] = []
    source_status = source.get("quality_status")
    stages.append(_stage(
        "observe", "collector",
        "complete" if source_status == "valid" else
        "blocked" if source_status in {"degraded", "quarantined"} else "pending",
        outcome=source_status, subject_id=source.get("snapshot_id"),
        next_action="refrescar y calificar las fuentes públicas",
    ))

    context_ready = (
        team.get("quality_status") == "valid" and bool(manifest.get("manifest_id"))
    )
    stages.append(_stage(
        "contextualize", "deterministic_coordinator",
        "complete" if context_ready else "pending",
        outcome="sealed" if context_ready else "incomplete",
        subject_id=manifest.get("manifest_id"),
        next_action="refrescar team state y sellar el manifest estratégico",
    ))

    research_status = research.get("status")
    stages.append(_stage(
        "research", "researcher",
        "complete" if research_status == "imported" else
        "degraded" if research_status in TERMINAL_BAD else "pending",
        outcome=research_status, subject_id=research.get("research_run_id"),
        next_action=(
            "diagnosticar el resultado rechazado; el flujo determinista puede continuar sin señales"
            if research_status in TERMINAL_BAD else
            "ejecutar o importar research cuando la cadencia lo requiera"
        ),
    ))

    envelope_status = envelope.get("status")
    envelope_complete = envelope_status in {"blocked", "staged"}
    stages.append(_stage(
        "propose_validate", "optimizer_validator",
        "complete" if envelope_complete else "pending",
        outcome=envelope_status, subject_id=envelope.get("envelope_id"),
        next_action="crear y validar el DecisionEnvelope desde el manifest vigente",
    ))

    deliberation_status = deliberation.get("status")
    stages.append(_stage(
        "deliberate", "strategist_critic",
        "complete" if deliberation_status in TERMINAL_DELIBERATIONS else
        "degraded" if deliberation_status in TERMINAL_BAD else "pending",
        outcome=deliberation_status, subject_id=deliberation.get("deliberation_id"),
        next_action=(
            "diagnosticar el worker; la policy determinista conserva autoridad"
            if deliberation_status in TERMINAL_BAD else
            "completar Strategist + Critic sobre el envelope vigente"
        ),
    ))

    plan_status = plan.get("status")
    plan_complete = plan_status in {"blocked", "authorized", "noop"}
    stages.append(_stage(
        "preflight", "policy_validator",
        "complete" if plan_complete else "pending",
        outcome=plan_status, subject_id=plan.get("plan_id"),
        next_action="sellar y evaluar el ExecutionPlan",
    ))

    attempt_status = attempt.get("status")
    if plan_status in {"blocked", "noop"}:
        execution_stage = _stage(
            "execute_verify", "executor_verifier", "skipped_policy",
            outcome=plan_status, subject_id=plan.get("plan_id"),
        )
    elif plan_status == "authorized":
        execution_stage = _stage(
            "execute_verify", "executor_verifier",
            "complete" if attempt_status == "verified" else
            "blocked" if attempt_status in TERMINAL_BAD | {"blocked"} else "pending",
            outcome=attempt_status, subject_id=attempt.get("execution_id"),
            next_action=(
                "detener retries y resolver el intento terminal antes de otra escritura"
                if attempt_status in TERMINAL_BAD | {"blocked"} else
                "preparar, ejecutar apply-once y verificar el estado posterior"
            ),
        )
    else:
        execution_stage = _stage(
            "execute_verify", "executor_verifier", "not_due",
            outcome="no_authorized_plan", next_action=None,
        )
    stages.append(execution_stage)

    settlement_due = bool(deadline and current >= deadline)
    stages.append(_stage(
        "settle", "official_settlement",
        "complete" if settlement.get("settlement_id") else
        "pending" if settlement_due else "not_due",
        outcome="settled" if settlement.get("settlement_id") else
        "due" if settlement_due else "predeadline",
        subject_id=settlement.get("settlement_id"),
        next_action="esperar datos oficiales finales y registrar settlement",
    ))

    if not settlement.get("settlement_id"):
        learning_stage = _stage(
            "review_learn", "reviewer", "not_due", outcome="awaiting_settlement",
        )
    elif not review.get("review_id"):
        learning_stage = _stage(
            "review_learn", "reviewer", "pending", outcome="review_missing",
            next_action="ejecutar review causal y proponer mejoras",
        )
    elif learning.get("lesson_count", 0) > 0:
        learning_stage = _stage(
            "review_learn", "reviewer", "complete", outcome="lesson_validated",
            subject_id=review.get("review_id"),
        )
    else:
        learning_stage = _stage(
            "review_learn", "reviewer", "pending", outcome="evaluation_pending",
            subject_id=review.get("review_id"),
            next_action="evaluar la propuesta y persistir o rechazar la lección",
        )
    stages.append(learning_stage)

    by_name = {row["name"]: row for row in stages}
    violations: list[dict] = []

    def require(stage_name: str, dependency: str, condition: bool) -> None:
        if condition and by_name[dependency]["status"] not in {
            "complete", "skipped_policy",
        }:
            violations.append({
                "code": "DOWNSTREAM_WITHOUT_DEPENDENCY",
                "stage": stage_name,
                "dependency": dependency,
            })

    require("contextualize", "observe", bool(manifest or team))
    require("propose_validate", "contextualize", bool(envelope))
    require("deliberate", "propose_validate", bool(deliberation))
    require("preflight", "propose_validate", bool(plan))
    if attempt:
        if plan_status != "authorized":
            violations.append({
                "code": "EXECUTION_WITHOUT_AUTHORIZED_PLAN",
                "stage": "execute_verify", "dependency": "preflight",
            })
    if review and not settlement:
        violations.append({
            "code": "REVIEW_WITHOUT_SETTLEMENT", "stage": "review_learn",
            "dependency": "settle",
        })
    if learning.get("lesson_count", 0) and not review:
        violations.append({
            "code": "LESSON_WITHOUT_REVIEW", "stage": "review_learn",
            "dependency": "review",
        })

    blocked = [row for row in stages if row["status"] == "blocked"]
    degraded = [row for row in stages if row["status"] == "degraded"]
    actionable = [
        row for row in stages
        if row["status"] == "pending" and row.get("next_action")
    ]
    verdict = (
        "blocked" if violations or blocked else
        "attention_required" if degraded or actionable else "safe_to_wait"
    )
    return {
        "schema": SCHEMA,
        "generated_at": current.isoformat(timespec="seconds"),
        "cycle_id": cycle.get("cycle_id"),
        "gw": cycle.get("gw"),
        "verdict": verdict,
        "stages": stages,
        "violations": violations,
        "next_actions": [
            {"stage": row["name"], "action": row["next_action"]}
            for row in actionable
        ],
        "roles": {
            "llm": ["researcher", "strategist", "critic"],
            "deterministic": [
                "coordinator", "optimizer", "validator", "policy",
                "executor", "verifier", "reviewer",
            ],
        },
        "runtime_mutated": False,
    }


def _row(con, query: str, parameters: tuple = ()) -> dict:
    found = con.execute(query, parameters).fetchone()
    return dict(found) if found else {}


def build_workflow(config: RuntimeConfig, db: OpsDB, *,
                   now: datetime | None = None) -> dict:
    """Construye el reporte del ciclo vigente desde el ledger canónico."""
    cycle = db.status().get("cycle") or {}
    cycle_id = str(cycle.get("cycle_id") or "")
    if not cycle_id:
        return evaluate_workflow({}, now=now)
    with db.connect(readonly=True) as con:
        observed = {
            "cycle": cycle,
            "source": _row(con,
                "SELECT snapshot_id,quality_status,captured_at FROM source_snapshots "
                "WHERE cycle_id=? ORDER BY captured_at DESC LIMIT 1", (cycle_id,)),
            "team_state": _row(con,
                "SELECT team_state_id,quality_status,observed_at FROM team_state_snapshots "
                "WHERE cycle_id=? ORDER BY observed_at DESC LIMIT 1", (cycle_id,)),
            "manifest": _row(con,
                "SELECT manifest_id,revision,created_at FROM cycle_manifests "
                "WHERE cycle_id=? ORDER BY revision DESC LIMIT 1", (cycle_id,)),
            "research": _row(con,
                "SELECT research_run_id,status,provider,finished_at FROM research_runs "
                "WHERE cycle_id=? ORDER BY queued_at DESC LIMIT 1", (cycle_id,)),
            "envelope": _row(con,
                "SELECT envelope_id,status,created_at FROM decision_envelopes "
                "WHERE cycle_id=? ORDER BY created_at DESC LIMIT 1", (cycle_id,)),
            "preflight": _row(con,
                "SELECT plan_id,status,risk_class,created_at FROM execution_plans "
                "WHERE cycle_id=? ORDER BY created_at DESC LIMIT 1", (cycle_id,)),
            "execution": _row(con,
                "SELECT a.execution_id,a.status,a.created_at FROM execution_attempts a "
                "JOIN execution_plans p ON p.plan_id=a.plan_id WHERE p.cycle_id=? "
                "ORDER BY a.created_at DESC LIMIT 1", (cycle_id,)),
            "settlement": _row(con,
                "SELECT settlement_id,settled_at FROM gameweek_settlements "
                "WHERE cycle_id=? ORDER BY settled_at DESC LIMIT 1", (cycle_id,)),
            "review": _row(con,
                "SELECT r.review_id,r.created_at FROM gameweek_reviews r "
                "JOIN gameweek_settlements s ON s.settlement_id=r.settlement_id "
                "WHERE s.cycle_id=? ORDER BY r.created_at DESC LIMIT 1", (cycle_id,)),
        }
        review_id = observed["review"].get("review_id")
        observed["learning"] = ({"lesson_count": int(con.execute(
            "SELECT COUNT(*) FROM lessons WHERE review_id=? AND status='validated'",
            (review_id,),
        ).fetchone()[0])} if review_id else {"lesson_count": 0})
    observed["deliberation"] = db.deliberation_status(cycle_id).get("latest") or {}
    report = evaluate_workflow(observed, now=now)
    budget = db.cost_report(config.agent_budget_policy(), season=config.season,
                            gw=cycle.get("gw"))
    report["budget"] = {
        "status": budget.get("status"),
        "orphaned_reservations": (budget.get("orphaned_reservations") or {}).get("status"),
    }
    if report["budget"]["orphaned_reservations"] == "observed":
        report["violations"].append({
            "code": "ORPHANED_AGENT_RESERVATION", "stage": "research",
            "dependency": "budget_ledger",
        })
        report["verdict"] = "blocked"
    return report


def orchestration_drill() -> dict:
    """Ensaya orden, fail-closed y deadline con fixtures, sin DB/runtime externo."""
    current = datetime(2026, 9, 4, 16, 0, tzinfo=timezone.utc)
    base = {
        "cycle": {"cycle_id": "drill-gw03", "gw": 3,
                  "deadline_at": "2026-09-04T17:30:00Z"},
        "source": {"snapshot_id": "snapshot_fixture", "quality_status": "valid"},
        "team_state": {"team_state_id": "team_fixture", "quality_status": "valid"},
        "manifest": {"manifest_id": "manifest_fixture"},
        "research": {"research_run_id": "research_fixture", "status": "imported"},
        "envelope": {"envelope_id": "envelope_fixture", "status": "blocked"},
        "deliberation": {"deliberation_id": "deliberation_fixture", "status": "blocked"},
        "preflight": {"plan_id": "plan_fixture", "status": "blocked"},
        "execution": {}, "settlement": {}, "review": {},
        "learning": {"lesson_count": 0},
    }
    valid = evaluate_workflow(base, now=current)
    failed_research = evaluate_workflow({
        **base, "research": {"research_run_id": "research_failed", "status": "failed"},
    }, now=current)
    authorized = evaluate_workflow({
        **base, "preflight": {"plan_id": "plan_authorized", "status": "authorized"},
    }, now=current)
    verified = evaluate_workflow({
        **base,
        "preflight": {"plan_id": "plan_authorized", "status": "authorized"},
        "execution": {"execution_id": "execution_fixture", "status": "verified"},
    }, now=current)
    orphan_execution = evaluate_workflow({
        **base, "preflight": {},
        "execution": {"execution_id": "execution_orphan", "status": "verified"},
    }, now=current)
    review_without_settlement = evaluate_workflow({
        **base, "review": {"review_id": "review_orphan"},
    }, now=current)
    after_deadline = evaluate_workflow(base, now=current + timedelta(hours=2))
    deterministic = evaluate_workflow(base, now=current)
    checks = {
        "valid_flow_has_no_dependency_violations": not valid["violations"],
        "blocked_envelope_is_terminal_fail_closed": next(
            row for row in valid["stages"] if row["name"] == "propose_validate"
        )["status"] == "complete",
        "blocked_preflight_skips_execution": next(
            row for row in valid["stages"] if row["name"] == "execute_verify"
        )["status"] == "skipped_policy",
        "research_failure_degrades_without_deadlock": (
            next(row for row in failed_research["stages"] if row["name"] == "research")
            ["status"] == "degraded" and not failed_research["violations"]
        ),
        "authorized_plan_requires_execution": next(
            row for row in authorized["stages"] if row["name"] == "execute_verify"
        )["status"] == "pending",
        "verified_attempt_completes_execution": next(
            row for row in verified["stages"] if row["name"] == "execute_verify"
        )["status"] == "complete",
        "execution_without_authority_is_rejected": any(
            row["code"] == "EXECUTION_WITHOUT_AUTHORIZED_PLAN"
            for row in orphan_execution["violations"]
        ),
        "review_without_settlement_is_rejected": any(
            row["code"] == "REVIEW_WITHOUT_SETTLEMENT"
            for row in review_without_settlement["violations"]
        ),
        "predeadline_settlement_is_not_fabricated": next(
            row for row in valid["stages"] if row["name"] == "settle"
        )["status"] == "not_due",
        "postdeadline_settlement_becomes_due": next(
            row for row in after_deadline["stages"] if row["name"] == "settle"
        )["status"] == "pending",
        "evaluation_is_deterministic": (
            sha256_json({k: v for k, v in valid.items() if k != "generated_at"})
            == sha256_json({k: v for k, v in deterministic.items() if k != "generated_at"})
        ),
        "fixture_never_mutates_runtime": valid["runtime_mutated"] is False,
    }
    return {
        "schema": DRILL_SCHEMA,
        "scenario": "agent_orchestration_deadline",
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
        "external_calls": 0,
        "runtime_mutated": False,
    }


def prometheus(report: dict) -> str:
    statuses = ("complete", "pending", "blocked", "degraded", "not_due", "skipped_policy")
    lines = [
        "# HELP mova_orchestration_status Current orchestration verdict.",
        "# TYPE mova_orchestration_status gauge",
        *[f'mova_orchestration_status{{status="{name}"}} '
          f'{1 if report.get("verdict") == name else 0}'
          for name in ("safe_to_wait", "attention_required", "blocked")],
        "# HELP mova_orchestration_stages Workflow stages by bounded state.",
        "# TYPE mova_orchestration_stages gauge",
    ]
    for stage in report.get("stages") or []:
        for status in statuses:
            lines.append(
                f'mova_orchestration_stages{{stage="{stage["name"]}",status="{status}"}} '
                f'{1 if stage.get("status") == status else 0}'
            )
    lines.extend([
        "# HELP mova_orchestration_dependency_violations Invalid downstream transitions.",
        "# TYPE mova_orchestration_dependency_violations gauge",
        f'mova_orchestration_dependency_violations {len(report.get("violations") or [])}',
        "",
    ])
    return "\n".join(lines)
