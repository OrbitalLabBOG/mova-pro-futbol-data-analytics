"""Cockpit read-only para humanos y agentes operadores.

Este módulo no crea un segundo control plane. Compone contratos existentes en
una vista pequeña y estable; ninguna función concede autoridad ni modifica el
runtime.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from mova_fpl.ops.alerts import channel_report
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB
from mova_fpl.ops.harness_scorecard import build_scorecard
from mova_fpl.ops.operator import build_safety, build_status
from mova_fpl.ops.orchestration import build_workflow
from mova_fpl.ops.readiness import build_readiness

SCHEMA = "mova-cockpit-v1"
TRIAGE_SCHEMA = "mova-triage-v1"


def _unit_active(host: dict, unit: str) -> bool:
    row = ((host.get("systemd") or {}).get(unit) or {})
    return row.get("active_state") == "active"


def _unit_failed(host: dict, unit: str) -> bool:
    row = ((host.get("systemd") or {}).get(unit) or {})
    return row.get("active_state") == "failed" or row.get("result") == "failed"


def _stage_map(workflow: dict) -> dict[str, dict]:
    return {str(row.get("name")): row for row in workflow.get("stages") or []}


def _gate_map(readiness: dict) -> dict[str, dict]:
    return {str(row.get("code")): row for row in readiness.get("gates") or []}


def _model_bundle(bundle: dict | None) -> dict:
    bundle = bundle or {}
    models = bundle.get("models") or {}
    return {
        "source": bundle.get("source"),
        "release_id": bundle.get("release_id"),
        "minutes": (models.get("minutes") or {}).get("version"),
        "points": (models.get("points") or {}).get("version"),
    }


def evaluate_cockpit(*, operator_status: dict, safety: dict, readiness: dict,
                     scorecard: dict, workflow: dict, costs: dict,
                     alert_channel: dict, alert_status: dict,
                     model_status: dict | None = None,
                     improvement: dict | None = None,
                     agent_routing: dict | None = None,
                     generated_at: str | None = None) -> dict:
    """Compone snapshots precomputados sin IO ni mutaciones."""
    gameweek = operator_status.get("gameweek") or {}
    runtime = operator_status.get("runtime") or {}
    controls = runtime.get("controls") or {}
    operations = operator_status.get("operations") or {}
    host = operator_status.get("host") or {}
    data = operator_status.get("data") or {}
    analytics = operator_status.get("analytics") or {}
    storage = operator_status.get("storage") or {}
    research = operator_status.get("research") or {}
    activation = readiness.get("activation") or {}
    stages = _stage_map(workflow)
    open_incidents = operations.get("open_incidents") or []
    critical = [row for row in open_incidents if row.get("severity") in {"P0", "P1"}]
    gw_cost = costs.get("gameweek") or {}
    month_cost = costs.get("month") or {}
    model_status = model_status or {}
    improvement = improvement or {}
    agent_routing = agent_routing or {}
    gates = _gate_map(readiness)
    improvement_costs = improvement.get("costs") or {}
    all_time_cost = improvement_costs.get("totals") or {}
    analytics_contract = model_status.get("analytics") or analytics
    scorecards = analytics_contract.get("latest_scorecards") or []
    projection_batches = analytics_contract.get("latest_projection_batches") or []
    proposal_counts = improvement.get("proposal_counts") or {}
    feedback_observed = {
        "model_scorecards": int((analytics_contract.get("counts") or {}).get("evaluations") or 0),
        "change_proposals": sum(int(value or 0) for value in proposal_counts.values()),
        "evaluations": len(improvement.get("evaluations") or []),
        "lessons": len(improvement.get("lessons") or []),
    }

    def gate_contract(code: str) -> dict:
        gate = gates.get(code) or {}
        return {
            "status": gate.get("status", "missing"),
            "observed": gate.get("observed"),
            "required": gate.get("required"),
            "next_action": gate.get("next_action"),
        }

    alerts: list[dict] = []
    for incident in critical[:5]:
        alerts.append({
            "severity": incident.get("severity"),
            "code": "OPEN_INCIDENT",
            "title": incident.get("title"),
            "incident_id": incident.get("incident_id"),
            "action": f"mova triage --incident-id {incident.get('incident_id')}",
        })
    if workflow.get("violations"):
        alerts.append({
            "severity": "P0", "code": "WORKFLOW_DEPENDENCY_VIOLATION",
            "title": "El ciclo agentic tiene una transición inválida",
            "action": "mova triage",
        })
    elif workflow.get("verdict") == "attention_required":
        degraded = [row for row in workflow.get("stages") or []
                    if row.get("status") in {"degraded", "blocked"}]
        alerts.append({
            "severity": "P2", "code": "WORKFLOW_ATTENTION_REQUIRED",
            "title": "El ciclo agentic requiere revisión",
            "detail": [row.get("name") for row in degraded],
            "action": "mova harness workflow",
        })
    if int(gw_cost.get("remaining_uses") or 0) <= 1:
        alerts.append({
            "severity": "P2", "code": "AGENT_BUDGET_LOW",
            "title": "Queda una o menos llamadas agentic en esta GW",
            "action": "mova cost report",
        })
    failed_services = sorted(
        name for name, row in (host.get("systemd") or {}).items()
        if name.endswith(".service") and (
            row.get("active_state") == "failed" or row.get("result") == "failed"
        )
    )
    if failed_services:
        alerts.append({
            "severity": "P2", "code": "SYSTEMD_SERVICE_FAILED",
            "title": "Un servicio programado requiere diagnóstico",
            "detail": failed_services,
            "action": "mova doctor --json",
        })
    if alert_channel.get("configured") is not True:
        alerts.append({
            "severity": "P2", "code": "EXTERNAL_ALERTS_LOCAL_ONLY",
            "title": "Las alertas todavía no tienen entrega externa",
            "action": "mova alerts channel",
        })

    severity_rank = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    alerts.sort(key=lambda row: severity_rank.get(str(row.get("severity")), 9))
    verdict = (
        "critical" if any(row.get("severity") == "P0" for row in alerts) else
        "attention_required" if alerts or safety.get("verdict") != "safe_to_wait" else
        "healthy"
    )

    functions = [
        {
            "code": "collector", "name": "Colector de datos",
            "enabled": _unit_active(host, "mova-fpl-collector.timer"),
            "status": (data.get("service") or {}).get("status"),
            "mode": "automatic_read_only",
        },
        {
            "code": "analytics", "name": "Modelos y scorecards",
            "enabled": _unit_active(host, "mova-fpl-analytics.timer"),
            "status": analytics.get("status"), "mode": "automatic_shadow",
        },
        {
            "code": "research", "name": "Investigación agentic",
            "enabled": _unit_active(host, "mova-fpl-research.timer"),
            "status": (
                "failed" if _unit_failed(host, "mova-fpl-research.service") else
                research.get("service_status")
                or ("conflicts" if research.get("conflicts") else None)
                or ("signals_ready" if research.get("signals") else "idle")
            ),
            "mode": "bounded_windows",
        },
        {
            "code": "strategist", "name": "Strategist + Critic",
            "enabled": _unit_active(host, "mova-fpl-research.timer"),
            "status": (operator_status.get("deliberation") or {}).get("status"),
            "mode": "bounded_shadow",
        },
        {
            "code": "browser_writes", "name": "Escrituras FPL",
            "enabled": bool(controls.get("browser_writes")),
            "status": "enabled" if controls.get("browser_writes") else "fail_closed",
            "mode": controls.get("action_level"),
        },
        {
            "code": "postgres_shadow", "name": "PostgreSQL shadow",
            "enabled": (storage.get("postgres") or {}).get("status") == "healthy",
            "status": (storage.get("postgres") or {}).get("read_parity", {}).get("status"),
            "mode": storage.get("postgres_role"),
        },
        {
            "code": "external_alerts", "name": "Alertas externas",
            "enabled": bool(alert_channel.get("configured")),
            "status": alert_channel.get("status"), "mode": "push",
        },
        {
            "code": "backup", "name": "Backup local",
            "enabled": _unit_active(host, "mova-fpl-backup.timer"),
            "status": (
                "active_local" if _unit_active(host, "mova-fpl-backup.timer")
                else "inactive"
            ),
            "mode": "scheduled",
        },
    ]

    return {
        "schema": SCHEMA,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "verdict": verdict,
        "headline": (
            "Intervención inmediata requerida" if verdict == "critical" else
            "Operación estable con pendientes" if verdict == "attention_required" else
            "Operación estable"
        ),
        "gameweek": {key: gameweek.get(key) for key in (
            "gw", "cycle_id", "deadline_at", "seconds_to_deadline", "phase", "readiness",
        )},
        "authority": {
            "mode": controls.get("mode"),
            "current_action_level": activation.get("current_action_level"),
            "technical_eligible_level": activation.get("technical_eligible_level"),
            "writes_enabled": activation.get("writes_enabled"),
            "kill_switch": controls.get("kill_switch"),
            "browser_writes": controls.get("browser_writes"),
            "promotion_is_automatic": False,
        },
        "functions": functions,
        "workflow": {
            "verdict": workflow.get("verdict"),
            "stages": [{key: row.get(key) for key in (
                "name", "owner", "status", "outcome", "subject_id", "next_action",
            )} for row in workflow.get("stages") or []],
            "violations": workflow.get("violations") or [],
        },
        "economics": {
            "status": costs.get("status"),
            "billing_mode": (
                "subscription" if int(all_time_cost.get("subscription_uses") or 0) > 0
                else "metered_or_unknown"
            ),
            "cost_known": (
                all_time_cost.get("estimated_cost_usd") is not None
                and int(all_time_cost.get("unknown_cost_uses") or 0) == 0
            ),
            "all_time": {key: all_time_cost.get(key) for key in (
                "uses", "input_tokens", "output_tokens", "subscription_uses",
                "estimated_cost_usd", "unknown_cost_uses",
            )},
            "by_provider_model": improvement_costs.get("by_provider_model") or [],
            "by_month": improvement_costs.get("by_month") or [],
            "gameweek": {key: gw_cost.get(key) for key in (
                "committed_tokens", "token_limit", "remaining_tokens",
                "committed_uses", "use_limit", "remaining_uses", "status",
            )},
            "month": {key: month_cost.get(key) for key in (
                "month", "committed_tokens", "token_limit", "remaining_tokens",
                "committed_uses", "use_limit", "remaining_uses", "status",
            )},
            "semantic_reuse": costs.get("semantic_reuse") or {},
        },
        "models": {
            "forecasting": {
                "active_bundle": _model_bundle(model_status.get("active_bundle")),
                "projection_batches": int(
                    (analytics_contract.get("counts") or {}).get("projections") or 0
                ),
                "evaluations": int(
                    (analytics_contract.get("counts") or {}).get("evaluations") or 0
                ),
                "drift_alerts": int(
                    (analytics_contract.get("counts") or {}).get("drift_alerts") or 0
                ),
                "latest_scorecard": ({key: scorecards[0].get(key) for key in (
                    "season", "gw", "variant", "drift_status", "evaluated_at",
                )} if scorecards else None),
                "latest_projection": ({key: projection_batches[0].get(key) for key in (
                    "batch_id", "season", "target_gw", "variant", "model_versions",
                    "cutoff_at", "generated_at", "status",
                )} if projection_batches else None),
            },
            "agents": {
                "provider": agent_routing.get("provider"),
                "researcher": agent_routing.get("researcher") or {},
                "strategist_critic": agent_routing.get("strategist_critic") or {},
            },
            "release": {
                "active": _model_bundle(model_status.get("active_bundle")),
                "registered": len(improvement.get("model_bundle_releases") or []),
                "promotion_is_automatic": False,
            },
        },
        "feedback": {
            "status": "observed" if feedback_observed["model_scorecards"] else "pending",
            "observed": feedback_observed,
            "proposal_counts": proposal_counts,
            "contracts": {
                "model_reconciliation": "automatic_after_fpl_data_checked",
                "causal_review": "automatic_after_verified_gameweek_closeout",
                "model_promotion": "explicit_release_gate",
            },
            "next_action": (
                None if feedback_observed["lessons"] > 0
                else "cerrar una GW con evidencia verificada y evaluar una propuesta causal"
            ),
        },
        "resilience": {
            "host_recovery": gate_contract("HOST_RECOVERY_DRILLS_PROVEN"),
            "snapshot_rejection": gate_contract("SNAPSHOT_REJECTION_PROVEN"),
            "browser_failure": gate_contract("BROWSER_FAILURE_DRILL_PROVEN"),
            "postgres_cycles": gate_contract("POSTGRES_THREE_GAMEWEEK_CYCLES"),
            "offsite_backup": gate_contract("OFF_HOST_BACKUP_CONFIGURED"),
            "offsite_restore": gate_contract("OFF_HOST_RESTORE_PROVEN"),
            "external_alerts": gate_contract("EXTERNAL_ALERT_CHANNEL_LIVE_PROVEN"),
        },
        "exit_shadow": {
            "status": "eligible" if (
                activation.get("technical_eligible_level") != "A0"
            ) else "evidence_pending",
            "current_level": activation.get("current_action_level"),
            "technical_eligible_level": activation.get("technical_eligible_level"),
            "promotion_is_automatic": False,
            "activation_blockers": activation.get("activation_blockers") or [],
            "next_actions": scorecard.get("next_actions") or [],
        },
        "quality": {
            "operator": operator_status.get("overall_status"),
            "safety": safety.get("verdict"),
            "scorecard": scorecard.get("overall_status"),
            "readiness": (scorecard.get("quality") or {}).get("readiness_pass_ratio"),
            "data": (data.get("service") or {}).get("status"),
            "analytics": analytics.get("status"),
            "postgres": (storage.get("postgres") or {}).get("status"),
        },
        "alerts": {
            "items": alerts,
            "open_incidents": len(open_incidents),
            "critical_open": len(critical),
            "outbox_due": alert_status.get("due"),
            "channel": alert_channel,
        },
        "runtime": {
            "git_sha": runtime.get("git_sha"),
            "latest_tick": operations.get("latest_tick"),
            "failed_jobs_last_24h": operations.get("failed_jobs_last_24h") or [],
        },
        "runtime_mutated": False,
    }


def build_cockpit(config: RuntimeConfig, db: OpsDB, *,
                  now: datetime | None = None) -> dict:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    from mova_fpl.ops.model_service import ModelOpsService

    improvement = db.improvement_status(season=config.season)
    return evaluate_cockpit(
        operator_status=build_status(config, db, now=current),
        safety=build_safety(config, db, now=current),
        readiness=build_readiness(config, db, now=current),
        scorecard=build_scorecard(config, db, now=current),
        workflow=build_workflow(config, db, now=current),
        costs=db.cost_report(config.agent_budget_policy(), season=config.season),
        alert_channel=channel_report(config, db),
        alert_status=db.outbox_status(),
        model_status=ModelOpsService(config, db).status(),
        improvement=improvement,
        agent_routing={
            "provider": config.research_provider,
            "researcher": {
                "model": config.research_model,
                "reasoning_effort": config.research_reasoning_effort,
            },
            "strategist_critic": {
                "model": config.deliberation_model,
                "reasoning_effort": config.deliberation_reasoning_effort,
            },
        },
        generated_at=current.isoformat(timespec="seconds"),
    )


def build_triage(config: RuntimeConfig, db: OpsDB, *,
                 incident_id: str | None = None,
                 now: datetime | None = None) -> dict:
    cockpit = build_cockpit(config, db, now=now)
    incidents = db.recent("incidents", 100)
    if incident_id:
        incidents = [row for row in incidents if row.get("incident_id") == incident_id]
        if not incidents:
            raise ValueError("incident not found")
    else:
        incidents = [row for row in incidents if row.get("status") != "resolved"][:10]
    correlation_ids = {str(row.get("correlation_id")) for row in incidents
                       if row.get("correlation_id")}
    jobs = db.recent("job_runs", 100)
    related_jobs = [row for row in jobs if (
        row.get("status") == "failed"
        or str(row.get("correlation_id")) in correlation_ids
        or any(row.get("job_id") == item.get("job_id") for item in incidents)
    )][:20]
    return {
        "schema": TRIAGE_SCHEMA,
        "generated_at": cockpit["generated_at"],
        "incident_filter": incident_id,
        "verdict": cockpit["verdict"],
        "summary": {
            "headline": cockpit["headline"],
            "gw": cockpit["gameweek"].get("gw"),
            "deadline_at": cockpit["gameweek"].get("deadline_at"),
            "git_sha": cockpit["runtime"].get("git_sha"),
            "workflow": cockpit["workflow"].get("verdict"),
            "safety": cockpit["quality"].get("safety"),
        },
        "alerts": cockpit["alerts"]["items"],
        "incidents": incidents,
        "related_jobs": related_jobs,
        "next_commands": [
            "mova status --json", "mova doctor --json", "mova harness workflow",
            "mova cost report", "mova alerts status",
        ],
        "runtime_mutated": False,
    }


def render_cockpit(payload: dict) -> str:
    gw = payload.get("gameweek") or {}
    authority = payload.get("authority") or {}
    economics = payload.get("economics") or {}
    gw_cost = economics.get("gameweek") or {}
    models = ((payload.get("models") or {}).get("forecasting") or {})
    active = models.get("active_bundle") or {}
    feedback = payload.get("feedback") or {}
    resilience = payload.get("resilience") or {}
    lines = [
        f"MOVA COCKPIT · {str(payload.get('verdict') or 'unknown').upper()}",
        str(payload.get("headline") or ""),
        (f"GW {gw.get('gw', '—')} · {gw.get('phase', '—')} · "
         f"deadline {gw.get('deadline_at', '—')}"),
        (f"Autoridad {authority.get('current_action_level', '—')} · "
         f"writes={authority.get('writes_enabled')} · kill_switch={authority.get('kill_switch')}"),
        (f"Agente GW: {gw_cost.get('committed_uses', 0)}/{gw_cost.get('use_limit', 0)} usos · "
         f"{gw_cost.get('remaining_tokens', 0)} tokens restantes"),
        (f"Modelos: points={active.get('points', '—')} · minutes={active.get('minutes', '—')} · "
         f"scorecards={models.get('evaluations', 0)}"),
        (f"Costo USD conocido={economics.get('cost_known')} · "
         f"billing={economics.get('billing_mode')}"),
        (f"Feedback: {feedback.get('status')} · "
         f"lessons={(feedback.get('observed') or {}).get('lessons', 0)}"),
        (f"DR host={(resilience.get('host_recovery') or {}).get('status')} · "
         f"offsite={(resilience.get('offsite_restore') or {}).get('status')}"),
        "",
        "FUNCIONES",
    ]
    for item in payload.get("functions") or []:
        mark = "ON " if item.get("enabled") else "OFF"
        lines.append(f"[{mark}] {item.get('name')}: {item.get('status')} ({item.get('mode')})")
    lines.extend(["", "CICLO"])
    for stage in (payload.get("workflow") or {}).get("stages") or []:
        lines.append(
            f"- {stage.get('name')}: {stage.get('status')} / {stage.get('outcome')}"
        )
    alerts = (payload.get("alerts") or {}).get("items") or []
    lines.extend(["", f"ALERTAS ({len(alerts)})"])
    lines.extend(
        f"- [{row.get('severity')}] {row.get('title')} · {row.get('action')}"
        for row in alerts
    )
    return "\n".join(lines)


def render_triage(payload: dict) -> str:
    lines = [
        f"MOVA TRIAGE · {str(payload.get('verdict') or 'unknown').upper()}",
        json.dumps(payload.get("summary") or {}, ensure_ascii=False, sort_keys=True),
        "",
        "INCIDENTES",
    ]
    incidents = payload.get("incidents") or []
    lines.extend(
        f"- [{row.get('severity')}] {row.get('incident_id')} · {row.get('status')} · {row.get('title')}"
        for row in incidents
    )
    lines.extend(["", "JOBS RELACIONADOS"])
    lines.extend(
        f"- {row.get('job_id')} · {row.get('job_type')} · {row.get('status')} · {row.get('error_code')}"
        for row in payload.get("related_jobs") or []
    )
    lines.extend(["", "SIGUIENTE LECTURA", *(
        f"- {command}" for command in payload.get("next_commands") or []
    )])
    return "\n".join(lines)
