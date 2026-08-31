"""Scorecard read-only de calidad, costo y autonomía del harness.

Readiness conserva el contrato de promoción. Este módulo no crea un segundo
gate ni concede autoridad: agrupa su evidencia por capacidad y la cruza con el
ledger económico y la memoria de mejora para que un operador pueda calificar
el harness completo en una sola consulta.
"""

from __future__ import annotations

from datetime import datetime, timezone

from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB
from mova_fpl.ops.readiness import build_readiness

SCHEMA = "mova-harness-scorecard-v1"

_GROUPS = {
    "operations": (
        "RUNTIME_HEALTHY", "NO_OPEN_P0_P1", "RESILIENCE_DRILL_PROVEN",
        "ORCHESTRATION_DRILL_PROVEN",
        "HOST_RECOVERY_DRILLS_PROVEN", "SNAPSHOT_REJECTION_PROVEN",
        "BROWSER_FAILURE_DRILL_PROVEN",
    ),
    "data_and_models": (
        "GAMEWEEK_INPUTS_READY", "PRIVATE_TEAM_STATE_FRESH",
        "DATA_SERVICE_HEALTHY", "ANALYTICS_SERVICE_HEALTHY",
        "APPROVED_CURRENT_PROJECTION",
    ),
    "agentic_decision": (
        "STRATEGIC_MANIFEST_PRESENT", "RESEARCH_EVIDENCE_CALIBRATED",
    ),
    "browser_execution": (
        "CAPTAINCY_DRIVER_PROVEN", "LINEUP_DRIVER_PROVEN", "R3_DRIVER_PROVEN",
    ),
    "durability": (
        "POSTGRES_SHADOW_PARITY", "POSTGRES_ROLE_SEPARATION",
        "POSTGRES_THREE_GAMEWEEK_CYCLES",
        "OFF_HOST_BACKUP_CONFIGURED", "OFF_HOST_RESTORE_PROVEN",
    ),
    "alerting": (
        "ALERT_CHANNEL_DRILL_PROVEN", "EXTERNAL_ALERT_CHANNEL_CONFIGURED",
        "EXTERNAL_ALERT_CHANNEL_LIVE_PROVEN",
    ),
}


def _dimension(name: str, gates: list[dict]) -> dict:
    counts = {
        status: sum(gate.get("status") == status for gate in gates)
        for status in ("pass", "pending", "blocked")
    }
    status = "blocked" if counts["blocked"] else "pending" if counts["pending"] else "pass"
    return {
        "name": name,
        "status": status,
        "summary": {**counts, "total": len(gates)},
        "gate_codes": [gate.get("code") for gate in gates],
        "unmet": [
            {"code": gate.get("code"), "status": gate.get("status"),
             "next_action": gate.get("next_action")}
            for gate in gates if gate.get("status") != "pass"
        ],
    }


def evaluate_scorecard(*, readiness: dict, cost_report: dict,
                       improvement: dict, deliberation: dict | None,
                       generated_at: str | None = None) -> dict:
    """Agrupa snapshots precomputados; no realiza IO ni modifica controles."""
    gates = readiness.get("gates") or []
    by_code = {gate.get("code"): gate for gate in gates}
    dimensions = []
    assigned: set[str] = set()
    for name, codes in _GROUPS.items():
        rows = [by_code[code] for code in codes if code in by_code]
        assigned.update(code for code in codes if code in by_code)
        dimension = _dimension(name, rows)
        if name == "agentic_decision":
            terminal = (deliberation or {}).get("status") in {
                "accepted", "review_required", "blocked",
            }
            dimension["deliberation"] = {
                "present": bool(deliberation),
                "terminal": terminal,
                "status": (deliberation or {}).get("status"),
                "provider": (deliberation or {}).get("provider"),
            }
            if not terminal:
                dimension["status"] = (
                    "blocked" if dimension["status"] == "blocked" else "pending"
                )
                dimension["unmet"].append({
                    "code": "TERMINAL_DELIBERATION_PRESENT", "status": "pending",
                    "next_action": "completar Strategist + Critic para el envelope vigente",
                })
        dimensions.append(dimension)

    unassigned = [gate for gate in gates if gate.get("code") not in assigned]
    if unassigned:
        dimensions.append(_dimension("other_readiness", unassigned))

    gw_cost = cost_report.get("gameweek") or {}
    month_cost = cost_report.get("month") or {}
    orphaned = (cost_report.get("orphaned_reservations") or {}).get("status") == "observed"
    overrun_status = (cost_report.get("job_overruns") or {}).get("status")
    overrun = overrun_status in {"observed", "unreviewed", "reviewed_pending"}
    cost_blocked = (
        orphaned or gw_cost.get("status") == "exceeded"
        or month_cost.get("status") == "exceeded"
    )
    cost_status = "blocked" if cost_blocked else "pending" if overrun else "pass"
    cost_unmet = []
    if cost_blocked:
        cost_unmet.append({
            "code": "AGENT_BUDGET_HEALTHY", "status": "blocked",
            "next_action": "resolver exceso agregado o reserva huérfana antes de otra inferencia",
        })
    elif overrun:
        cost_unmet.append({
            "code": ("AGENT_JOB_OVERRUN_REVIEWED" if overrun_status in {
                "observed", "unreviewed"
            } else "AGENT_JOB_OVERRUN_FOLLOWUP_VERIFIED"),
            "status": "pending",
            "next_action": (
                "revisar el job que excedió su límite y registrar una transición auditada"
                if overrun_status in {"observed", "unreviewed"} else
                "verificar un run posterior equivalente dentro del límite y resolver el overrun"
            ),
        })
    cost_dimension = {
        "name": "economics",
        "status": cost_status,
        "report_status": cost_report.get("status"),
        "gameweek": {key: gw_cost.get(key) for key in (
            "committed_tokens", "token_limit", "remaining_tokens",
            "committed_uses", "use_limit", "remaining_uses", "status",
        )},
        "month": {key: month_cost.get(key) for key in (
            "month", "committed_tokens", "token_limit", "remaining_tokens",
            "committed_uses", "use_limit", "remaining_uses", "status",
        )},
        "semantic_reuse": cost_report.get("semantic_reuse") or {},
        "job_overruns": cost_report.get("job_overruns") or {},
        "orphaned_reservations": cost_report.get("orphaned_reservations") or {},
        "unmet": cost_unmet,
    }
    dimensions.append(cost_dimension)

    proposals = improvement.get("proposal_counts") or {}
    lessons = improvement.get("lessons") or []
    evaluations = improvement.get("evaluations") or []
    reviews_observed = sum(int(value or 0) for value in proposals.values())
    learning_pass = reviews_observed > 0 and len(lessons) > 0
    dimensions.append({
        "name": "continuous_learning",
        "status": "pass" if learning_pass else "pending",
        "observed": {
            "proposals": reviews_observed,
            "lessons": len(lessons),
            "evaluations": len(evaluations),
            "proposal_counts": proposals,
        },
        "unmet": ([] if learning_pass else [{
            "code": "LEARNING_LOOP_OBSERVED", "status": "pending",
            "next_action": "cerrar una GW y registrar propuesta, evaluación y lección causal",
        }]),
    })

    statuses = [row["status"] for row in dimensions]
    overall = "blocked" if "blocked" in statuses else "pending" if "pending" in statuses else "pass"
    gate_counts = {
        status: sum(gate.get("status") == status for gate in gates)
        for status in ("pass", "pending", "blocked")
    }
    pass_ratio = round(gate_counts["pass"] / len(gates), 4) if gates else 0.0
    next_actions = []
    seen = set()
    for dimension in dimensions:
        for item in dimension.get("unmet") or []:
            code = item.get("code")
            if code not in seen:
                seen.add(code)
                next_actions.append({**item, "dimension": dimension["name"]})
    activation = readiness.get("activation") or {}
    return {
        "schema": SCHEMA,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "season": readiness.get("season"),
        "cycle_id": readiness.get("cycle_id"),
        "gw": readiness.get("gw"),
        "overall_status": overall,
        "quality": {
            "readiness_pass_ratio": pass_ratio,
            "gates": {**gate_counts, "total": len(gates)},
            "technical_eligible_level": activation.get("technical_eligible_level"),
        },
        "authority": {
            "current_action_level": activation.get("current_action_level"),
            "promotion_is_automatic": False,
            "writes_enabled": activation.get("writes_enabled"),
            "activation_blockers": activation.get("activation_blockers") or [],
        },
        "dimensions": dimensions,
        "next_actions": next_actions,
    }


def build_scorecard(config: RuntimeConfig, db: OpsDB, *,
                    now: datetime | None = None) -> dict:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    readiness = build_readiness(config, db, now=current)
    improvement = db.improvement_status(season=config.season)
    return evaluate_scorecard(
        readiness=readiness,
        cost_report=db.cost_report(config.agent_budget_policy(), season=config.season),
        improvement=improvement,
        deliberation=(db.deliberation_status().get("latest") or {}),
        generated_at=current.isoformat(timespec="seconds"),
    )


def prometheus(report: dict) -> str:
    status = report.get("overall_status", "blocked")
    quality = report.get("quality") or {}
    lines = [
        "# HELP mova_harness_scorecard_up Harness scorecard contract availability.",
        "# TYPE mova_harness_scorecard_up gauge",
        "mova_harness_scorecard_up 1",
        "# HELP mova_harness_scorecard_status Current aggregate harness status.",
        "# TYPE mova_harness_scorecard_status gauge",
        *[f'mova_harness_scorecard_status{{status="{name}"}} {1 if name == status else 0}'
          for name in ("pass", "pending", "blocked")],
        "# HELP mova_harness_readiness_pass_ratio Fraction of readiness gates passing.",
        "# TYPE mova_harness_readiness_pass_ratio gauge",
        f'mova_harness_readiness_pass_ratio {float(quality.get("readiness_pass_ratio") or 0):.4f}',
        "# HELP mova_harness_dimension_status Harness dimensions by state.",
        "# TYPE mova_harness_dimension_status gauge",
    ]
    for dimension in report.get("dimensions") or []:
        for name in ("pass", "pending", "blocked"):
            lines.append(
                f'mova_harness_dimension_status{{dimension="{dimension["name"]}",status="{name}"}} '
                f'{1 if dimension.get("status") == name else 0}'
            )
    return "\n".join(lines) + "\n"
