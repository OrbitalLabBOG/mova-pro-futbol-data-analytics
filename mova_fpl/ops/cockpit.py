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


def _stage_map(workflow: dict) -> dict[str, dict]:
    return {str(row.get("name")): row for row in workflow.get("stages") or []}


def evaluate_cockpit(*, operator_status: dict, safety: dict, readiness: dict,
                     scorecard: dict, workflow: dict, costs: dict,
                     alert_channel: dict, alert_status: dict,
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
    return evaluate_cockpit(
        operator_status=build_status(config, db, now=current),
        safety=build_safety(config, db, now=current),
        readiness=build_readiness(config, db, now=current),
        scorecard=build_scorecard(config, db, now=current),
        workflow=build_workflow(config, db, now=current),
        costs=db.cost_report(config.agent_budget_policy(), season=config.season),
        alert_channel=channel_report(config, db),
        alert_status=db.outbox_status(),
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
    lines = [
        f"MOVA COCKPIT · {str(payload.get('verdict') or 'unknown').upper()}",
        str(payload.get("headline") or ""),
        (f"GW {gw.get('gw', '—')} · {gw.get('phase', '—')} · "
         f"deadline {gw.get('deadline_at', '—')}"),
        (f"Autoridad {authority.get('current_action_level', '—')} · "
         f"writes={authority.get('writes_enabled')} · kill_switch={authority.get('kill_switch')}"),
        (f"Agente GW: {gw_cost.get('committed_uses', 0)}/{gw_cost.get('use_limit', 0)} usos · "
         f"{gw_cost.get('remaining_tokens', 0)} tokens restantes"),
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
