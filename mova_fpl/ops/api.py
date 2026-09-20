"""API local de observabilidad, deliberadamente de solo lectura."""

from __future__ import annotations

import html
import json
import logging
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB
from mova_fpl.ops.operator import build_safety, build_status

LOG = logging.getLogger(__name__)


def _json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")


def _human_deadline(value: str | None, seconds: int | None) -> tuple[str, str]:
    """Convierte el deadline técnico en una frase breve para el owner."""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        local = parsed.astimezone(ZoneInfo("America/Bogota"))
        days = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
        months = ("enero", "febrero", "marzo", "abril", "mayo", "junio",
                  "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre")
        hour = local.hour % 12 or 12
        period = "a. m." if local.hour < 12 else "p. m."
        label = (f"{days[local.weekday()].capitalize()} {local.day} de "
                 f"{months[local.month - 1]} · {hour}:{local.minute:02d} {period}")
    except (TypeError, ValueError):
        label = "Por confirmar"

    remaining = int(seconds or 0)
    if remaining <= 0:
        relative = "El plazo ya venció"
    elif remaining >= 86400:
        whole_days, remainder = divmod(remaining, 86400)
        hours = remainder // 3600
        day_unit = "día" if whole_days == 1 else "días"
        hour_unit = "hora" if hours == 1 else "horas"
        relative = f"Faltan {whole_days} {day_unit}" + (
            f" y {hours} {hour_unit}" if hours else ""
        )
    elif remaining >= 3600:
        hours, remainder = divmod(remaining, 3600)
        minutes = remainder // 60
        hour_unit = "hora" if hours == 1 else "horas"
        relative = f"Faltan {hours} {hour_unit}" + (
            f" y {minutes} min" if minutes else ""
        )
    else:
        relative = f"Faltan {max(1, remaining // 60)} minutos"
    return label, relative


def _dashboard_state(cockpit: dict) -> dict:
    """Traduce el contrato técnico a estados públicos sin elevar autoridad."""
    gameweek = cockpit.get("gameweek") or {}
    authority = cockpit.get("authority") or {}
    quality = cockpit.get("quality") or {}
    workflow = cockpit.get("workflow") or {}
    alerts_contract = cockpit.get("alerts") or {}
    alerts = alerts_contract.get("items") or []
    critical = [row for row in alerts if row.get("severity") in {"P0", "P1"}]
    core_states = [quality.get(key) for key in ("operator", "data", "analytics", "postgres")]
    core_unhealthy = any(value not in {"healthy", "pass"} for value in core_states)
    safety = quality.get("safety")
    readiness = quality.get("readiness_summary") or {}
    pending_gates = int(readiness.get("pending") or 0) + int(readiness.get("blocked") or 0)
    stages = workflow.get("stages") or []
    cycle_pending = workflow.get("verdict") == "attention_required" or any(
        row.get("status") in {"pending", "blocked", "degraded"} for row in stages
    )
    action_level = str(authority.get("current_action_level") or "A0")
    writes_enabled = authority.get("writes_enabled") is True
    alert_channel = alerts_contract.get("channel") or {}

    danger = bool(critical or core_unhealthy or safety == "unsafe")
    attention = not danger and bool(
        cockpit.get("verdict") == "attention_required"
        or quality.get("scorecard") not in {"healthy", "pass", "ready"}
        or pending_gates
        or cycle_pending
        or action_level != "A3"
        or not writes_enabled
        or alert_channel.get("configured") is not True
    )
    tone = "danger" if danger else "attention" if attention else "ok"

    if danger:
        headline = "Intervención requerida"
        summary = "El runtime reporta un problema que necesita revisión de ORBIX."
        action_value = "Avisar a ORBIX ahora"
        action_copy = "Comparte una captura de esta pantalla para iniciar el diagnóstico."
    elif attention:
        cycle_label = "pendiente" if cycle_pending else "listo"
        headline = (
            f"Sistema operativo · ciclo GW{gameweek.get('gw') or '—'} {cycle_label} · "
            f"autonomía {action_level}"
        )
        summary = "La infraestructura responde, pero el ciclo y la autonomía aún no están cerrados."
        action_value = "No intervenir todavía"
        if alert_channel.get("configured") is not True:
            action_copy = (
                "Las alertas externas siguen locales; revisa esta pantalla antes del cierre."
            )
        else:
            action_copy = "El sistema permanece fail-closed mientras completa sus controles."
    else:
        headline = f"Sistema operativo · ciclo GW{gameweek.get('gw') or '—'} listo"
        summary = "Runtime, ciclo y controles observados están listos."
        action_value = "Ninguna"
        action_copy = "La pantalla seguirá actualizando el estado cada 30 segundos."

    health_value = "Requiere revisión" if danger else "En línea"
    health_copy = (
        "Hay un fallo o riesgo operativo activo."
        if danger else "Servicios, datos y modelos responden en el corte observado."
    )
    cycle_value = "Pendiente" if cycle_pending else "Listo"
    cycle_copy = (
        "Research, validación o preflight aún no han cerrado."
        if cycle_pending else "El flujo observado no reporta etapas pendientes."
    )
    autonomy_value = (
        f"{action_level} · Escrituras habilitadas"
        if writes_enabled else f"{action_level} · Solo lectura"
    )
    total_gates = int(readiness.get("total") or 0)
    pass_gates = int(readiness.get("pass") or 0)
    autonomy_copy = (
        f"{pass_gates}/{total_gates} controles listos · {pending_gates} "
        f"{'pendiente' if pending_gates == 1 else 'pendientes'}."
        if total_gates else "La promoción requiere evidencia y aprobación explícitas."
    )
    return {
        "tone": tone,
        "icon": "!" if danger else "·" if attention else "✓",
        "headline": headline,
        "summary": summary,
        "health_value": health_value,
        "health_copy": health_copy,
        "cycle_value": cycle_value,
        "cycle_copy": cycle_copy,
        "autonomy_value": autonomy_value,
        "autonomy_copy": autonomy_copy,
        "action_value": action_value,
        "action_copy": action_copy,
        "alerts": alerts,
    }


def _dashboard(cockpit: dict) -> bytes:
    esc = lambda value: html.escape(str(value if value is not None else "—"))
    gameweek = cockpit.get("gameweek") or {}
    authority = cockpit.get("authority") or {}
    economics = cockpit.get("economics") or {}
    gw_cost = economics.get("gameweek") or {}
    view = _dashboard_state(cockpit)
    alerts = view["alerts"]
    deadline, deadline_relative = _human_deadline(
        gameweek.get("deadline_at"), gameweek.get("seconds_to_deadline"),
    )
    internal_summary = (
        f"{len(alerts)} {'señal operativa visible' if len(alerts) == 1 else 'señales operativas visibles'}"
        if alerts else "Sin alertas activas"
    )
    problem_rows = "".join(
        f"<li><strong>{esc(row.get('severity'))}</strong> · {esc(row.get('title'))}</li>"
        for row in alerts[:5]
    )
    if not problem_rows:
        problem_rows = "<li>No hay alertas activas en el corte observado.</li>"
    body = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<meta http-equiv="refresh" content="30"><title>MOVA · Estado</title>
<style>
:root {{ color-scheme:dark;background:#071019;color:#f4f8fc;font-family:"Trebuchet MS",sans-serif }}
* {{ box-sizing:border-box }} body {{ margin:0;min-height:100vh }}
.shell {{ width:min(980px,calc(100% - 32px));margin:0 auto;padding:34px 0 48px }}
header {{ display:flex;align-items:center;justify-content:space-between;gap:20px;margin-bottom:28px }}
.brand {{ font-family:Georgia,serif;font-size:1.45rem;font-weight:700;letter-spacing:-.02em }}
.refresh {{ color:#87a0b8;font-size:.84rem }}
.status {{ display:grid;grid-template-columns:84px 1fr;gap:24px;align-items:center;border:1px solid #28594b;background:#0b211c;border-radius:28px;padding:34px;margin-bottom:22px }}
.status.attention {{ border-color:#81631f;background:#241d0c }}
.status.danger {{ border-color:#8f3540;background:#2a1015 }}
.beacon {{ width:76px;height:76px;border-radius:50%;display:grid;place-items:center;background:#36d39a;color:#052319;font:700 2.4rem Georgia,serif;box-shadow:0 0 0 12px rgba(54,211,154,.09) }}
.attention .beacon {{ background:#f4bd4f;color:#2b1a00;box-shadow:0 0 0 12px rgba(244,189,79,.09) }}
.danger .beacon {{ background:#ff7182;color:#2a0710;box-shadow:0 0 0 12px rgba(255,113,130,.09) }}
h1 {{ font:700 clamp(2rem,5vw,3.7rem)/1.02 Georgia,serif;letter-spacing:-.045em;margin:0 0 10px }}
.status p {{ color:#b7c9c2;font-size:1.12rem;line-height:1.5;margin:0 }} .attention p {{ color:#decfa8 }} .danger p {{ color:#f1bcc2 }}
.cards {{ display:grid;grid-template-columns:repeat(3,1fr);gap:14px }}
.card {{ min-height:172px;padding:24px;border:1px solid #23384a;background:#0d1925;border-radius:20px;display:flex;flex-direction:column;justify-content:space-between }}
.label {{ color:#88a2bb;font-size:.76rem;letter-spacing:.12em;text-transform:uppercase }}
.value {{ font:700 clamp(1.55rem,3vw,2.2rem)/1.08 Georgia,serif;margin:14px 0 8px;letter-spacing:-.025em }}
.card p {{ color:#afc1d1;line-height:1.45;margin:0 }}
.deadline {{ color:#718aa1;font-size:.84rem;margin-top:14px }}
.action-strip {{ margin-top:14px;padding:21px 24px;border:1px solid #33485b;background:#0b1620;border-radius:18px;display:grid;grid-template-columns:minmax(160px,.55fr) 1fr;gap:20px;align-items:center }}
.attention ~ .cards + .action-strip {{ border-color:#81631f }} .danger ~ .cards + .action-strip {{ border-color:#8f3540 }}
.action-strip .value {{ margin:7px 0 0;font-size:1.45rem }} .action-strip p {{ color:#afc1d1;line-height:1.45;margin:0 }}
.under-control {{ text-align:center;color:#7890a6;font-size:.86rem;margin:20px 0 0 }}
details {{ margin-top:34px;border-top:1px solid #1d3041;padding-top:18px;color:#8fa5b9 }}
summary {{ cursor:pointer;width:max-content;min-height:44px;display:flex;align-items:center;color:#9bb2c7;font-weight:700 }}
summary:focus-visible {{ outline:2px solid #f4bd4f;outline-offset:4px;border-radius:3px }}
details p,details li {{ font-size:.9rem;line-height:1.55 }}
footer {{ color:#60778d;font-size:.75rem;margin-top:26px }}
@media(max-width:720px) {{ .shell {{ width:min(100% - 22px,980px);padding-top:22px }} header {{ display:block }} .refresh {{ margin-top:7px;text-align:left }} .status {{ grid-template-columns:1fr;padding:26px }} .beacon {{ width:58px;height:58px;font-size:1.8rem }} .cards {{ grid-template-columns:1fr }} .card {{ min-height:132px }} .action-strip {{ grid-template-columns:1fr }} }}
@media(prefers-reduced-motion:reduce) {{ * {{ scroll-behavior:auto!important }} }}
</style></head><body>
<div class="shell"><header><div class="brand">MOVA Fantasy Fútbol</div><div class="refresh">Estado en vivo · se actualiza solo</div></header>
<main><section class="status {view['tone']}" aria-labelledby="main-status"><div class="beacon" aria-hidden="true">{view['icon']}</div><div><h1 id="main-status">{esc(view['headline'])}</h1><p>{esc(view['summary'])}</p></div></section>
<section class="cards" aria-label="Resumen principal">
<article class="card"><div><div class="label">Salud técnica</div><div class="value">{esc(view['health_value'])}</div></div><p>{esc(view['health_copy'])}</p></article>
<article class="card"><div><div class="label">Ciclo · GW {esc(gameweek.get('gw'))}</div><div class="value">{esc(view['cycle_value'])}</div></div><p>{esc(view['cycle_copy'])}</p><div class="deadline">{esc(deadline)} · {esc(deadline_relative)}</div></article>
<article class="card"><div><div class="label">Autonomía</div><div class="value">{esc(view['autonomy_value'])}</div></div><p>{esc(view['autonomy_copy'])}</p></article>
</section><section class="action-strip" aria-labelledby="owner-action"><div><div class="label">Tu acción</div><div class="value" id="owner-action">{esc(view['action_value'])}</div></div><p>{esc(view['action_copy'])}</p></section><p class="under-control">{esc(internal_summary)}</p>
<details><summary>Ver información técnica</summary><p>Autoridad {esc(authority.get('current_action_level'))} · escrituras {"habilitadas" if authority.get('writes_enabled') else "desactivadas"} · revisión {esc((cockpit.get('runtime') or {}).get('git_sha'))}</p><p>Presupuesto interno: {esc(gw_cost.get('committed_uses'))}/{esc(gw_cost.get('use_limit'))} ejecuciones en esta jornada.</p><ul>{problem_rows}</ul></details>
</main><footer>Lectura segura · se actualiza automáticamente cada 30 segundos</footer></div>
</body></html>"""
    return body.encode("utf-8")


def make_handler(db: OpsDB, config: RuntimeConfig | None = None):
    runtime = config or RuntimeConfig()

    class Handler(BaseHTTPRequestHandler):
        server_version = "MOVAOps/1.0"

        def log_message(self, fmt: str, *args) -> None:
            LOG.info("http_access", extra={"event": "http_access", "detail": {
                "remote": self.client_address[0], "request": fmt % args,
            }})

        def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - contrato BaseHTTPRequestHandler
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/healthz":
                    self._send(HTTPStatus.OK, b'{"status":"ok"}', "application/json")
                    return
                if parsed.path == "/readyz":
                    db.quick_check()
                    self._send(HTTPStatus.OK, b'{"status":"ready"}', "application/json")
                    return
                if parsed.path == "/metrics":
                    metrics = db.prometheus()
                    from mova_fpl.ops.watchdog import (
                        agent_queue_prometheus, assess_agent_queue,
                        assess_workflow_deadline, workflow_deadline_prometheus,
                    )
                    metrics += agent_queue_prometheus(
                        assess_agent_queue(runtime, db)
                    )
                    metrics += workflow_deadline_prometheus(
                        assess_workflow_deadline(runtime, db)
                    )
                    from mova_fpl.ops.alerts import channel_prometheus, channel_report
                    metrics += channel_prometheus(channel_report(runtime, db))
                    metrics += db.cost_prometheus(
                        runtime.agent_budget_policy(), season=runtime.season
                    )
                    metrics += db.agent_worker_attempt_prometheus()
                    metrics += db.model_release_prometheus()
                    try:
                        from mova_fpl.ops.harness_scorecard import (
                            build_scorecard, prometheus as harness_prometheus,
                        )
                        metrics += harness_prometheus(build_scorecard(runtime, db))
                    except Exception:
                        metrics += "mova_harness_scorecard_up 0\n"
                    try:
                        from mova_fpl.ops.orchestration import (
                            build_workflow, prometheus as orchestration_prometheus,
                        )
                        metrics += orchestration_prometheus(build_workflow(runtime, db))
                    except Exception:
                        metrics += "mova_orchestration_status{status=\"blocked\"} 1\n"
                    try:
                        from mova_fpl.postgres.store import (
                            prometheus as postgres_prometheus,
                            read_status as read_postgres_status,
                            status as postgres_status,
                        )
                        pg_state = (postgres_status(runtime)
                                    if runtime.postgres_credential_file.is_file()
                                    else read_postgres_status(runtime))
                        metrics += postgres_prometheus(pg_state)
                    except Exception:
                        metrics += "mova_postgres_shadow_up 0\n"
                    try:
                        from mova_fpl.ops.collector.store import (
                            CollectorStore, prometheus, read_status,
                        )
                        state = (CollectorStore(runtime).status()
                                 if runtime.postgres_credential_file.is_file()
                                 else read_status(runtime))
                        metrics += prometheus(state)
                    except Exception:  # data service puede no estar inicializado aún
                        metrics += "mova_data_service_up 0\n"
                    try:
                        from mova_fpl.ops.analytics_store import (
                            AnalyticsStore, prometheus as analytics_prometheus,
                            read_status as read_analytics_status,
                        )
                        analytics = (AnalyticsStore(runtime).status()
                                     if runtime.postgres_credential_file.is_file()
                                     else read_analytics_status(runtime))
                        metrics += analytics_prometheus(analytics)
                    except Exception:
                        metrics += "mova_analytics_service_up 0\n"
                    try:
                        from mova_fpl.ops.readiness import (
                            build_readiness, prometheus as readiness_prometheus,
                        )
                        metrics += readiness_prometheus(build_readiness(runtime, db))
                    except Exception:
                        metrics += "mova_autonomy_readiness_up 0\n"
                    self._send(HTTPStatus.OK, metrics.encode(),
                               "text/plain; version=0.0.4; charset=utf-8")
                    return
                if parsed.path == "/api/v1/agent-queue":
                    from mova_fpl.ops.watchdog import assess_agent_queue

                    payload = assess_agent_queue(runtime, db)
                    self._send(
                        HTTPStatus.OK if payload["healthy"]
                        else HTTPStatus.SERVICE_UNAVAILABLE,
                        _json_bytes(payload), "application/json; charset=utf-8",
                    )
                    return
                if parsed.path == "/api/v1/agent-attempts":
                    self._send(
                        HTTPStatus.OK, _json_bytes(db.agent_worker_attempt_status()),
                        "application/json; charset=utf-8",
                    )
                    return
                if parsed.path in {"/", "/dashboard"}:
                    from mova_fpl.ops.cockpit import build_cockpit

                    self._send(HTTPStatus.OK, _dashboard(build_cockpit(runtime, db)),
                               "text/html; charset=utf-8")
                    return
                if parsed.path == "/api/v1/cockpit":
                    from mova_fpl.ops.cockpit import build_cockpit

                    self._send(
                        HTTPStatus.OK, _json_bytes(build_cockpit(runtime, db)),
                        "application/json; charset=utf-8",
                    )
                    return
                if parsed.path == "/api/v1/triage":
                    from mova_fpl.ops.cockpit import build_triage

                    incident_id = parse_qs(parsed.query).get("incident_id", [None])[0]
                    self._send(
                        HTTPStatus.OK,
                        _json_bytes(build_triage(runtime, db, incident_id=incident_id)),
                        "application/json; charset=utf-8",
                    )
                    return
                if parsed.path == "/api/v1/data":
                    from mova_fpl.ops.collector.store import CollectorStore, read_status
                    payload = (CollectorStore(runtime).status()
                               if runtime.postgres_credential_file.is_file()
                               else read_status(runtime))
                    self._send(HTTPStatus.OK, _json_bytes(payload),
                               "application/json; charset=utf-8")
                    return
                if parsed.path == "/api/v1/data/coverage":
                    from mova_fpl.ops.collector.store import (
                        CollectorStore, read_coverage,
                    )
                    payload = (CollectorStore(runtime).coverage()
                               if runtime.postgres_credential_file.is_file()
                               else read_coverage(runtime))
                    self._send(HTTPStatus.OK if payload["status"] == "complete"
                               else HTTPStatus.SERVICE_UNAVAILABLE,
                               _json_bytes(payload), "application/json; charset=utf-8")
                    return
                if parsed.path in {"/api/v1/analytics", "/api/v1/analytics/scorecards"}:
                    from mova_fpl.ops.analytics_store import AnalyticsStore, read_status
                    payload = (AnalyticsStore(runtime).status()
                               if runtime.postgres_credential_file.is_file()
                               else read_status(runtime))
                    if parsed.path.endswith("/scorecards"):
                        raw = parse_qs(parsed.query).get("limit", ["20"])[0]
                        limit = max(1, min(int(raw), 100))
                        payload = {"schema": "mova-model-scorecards-v1", "limit": limit,
                                   "items": payload.get("latest_scorecards", [])[:limit]}
                    self._send(HTTPStatus.OK, _json_bytes(payload),
                               "application/json; charset=utf-8")
                    return
                if parsed.path.startswith("/api/v1/analytics/gw/"):
                    from mova_fpl.ops.analytics_store import AnalyticsStore, read_status
                    try:
                        gw = int(parsed.path.rsplit("/", 1)[-1])
                    except ValueError as exc:
                        raise ValueError("gw inválida") from exc
                    if not 1 <= gw <= 38:
                        raise ValueError("gw debe estar entre 1 y 38")
                    state = (AnalyticsStore(runtime).status(limit=100)
                             if runtime.postgres_credential_file.is_file()
                             else read_status(runtime))
                    items = [item for item in state.get("latest_scorecards", [])
                             if int(item["gw"]) == gw]
                    self._send(HTTPStatus.OK if items else HTTPStatus.NOT_FOUND,
                               _json_bytes({"schema": "mova-model-scorecards-v1",
                                            "gw": gw, "items": items}),
                               "application/json; charset=utf-8")
                    return
                if parsed.path == "/api/v1/improvement":
                    query = parse_qs(parsed.query)
                    season = query.get("season", [None])[0]
                    raw_gw = query.get("gw", [None])[0]
                    gw = int(raw_gw) if raw_gw is not None else None
                    if gw is not None and not 1 <= gw <= 38:
                        raise ValueError("gw debe estar entre 1 y 38")
                    self._send(
                        HTTPStatus.OK,
                        _json_bytes(db.improvement_status(season=season, gw=gw)),
                        "application/json; charset=utf-8",
                    )
                    return
                if parsed.path == "/api/v1/costs":
                    query = parse_qs(parsed.query)
                    raw_gw = query.get("gw", [None])[0]
                    gw = int(raw_gw) if raw_gw is not None else None
                    if gw is not None and not 1 <= gw <= 38:
                        raise ValueError("gw debe estar entre 1 y 38")
                    payload = db.cost_report(
                        runtime.agent_budget_policy(), season=runtime.season,
                        gw=gw, month=query.get("month", [None])[0],
                    )
                    self._send(HTTPStatus.OK, _json_bytes(payload),
                               "application/json; charset=utf-8")
                    return
                if parsed.path == "/api/v1/research/coverage":
                    self._send(
                        HTTPStatus.OK, _json_bytes(db.research_coverage()),
                        "application/json; charset=utf-8",
                    )
                    return
                if parsed.path == "/api/v1/readiness":
                    from mova_fpl.ops.readiness import build_readiness

                    self._send(
                        HTTPStatus.OK, _json_bytes(build_readiness(runtime, db)),
                        "application/json; charset=utf-8",
                    )
                    return
                if parsed.path == "/api/v1/harness-scorecard":
                    from mova_fpl.ops.harness_scorecard import build_scorecard

                    self._send(
                        HTTPStatus.OK, _json_bytes(build_scorecard(runtime, db)),
                        "application/json; charset=utf-8",
                    )
                    return
                if parsed.path == "/api/v1/orchestration":
                    from mova_fpl.ops.orchestration import build_workflow

                    self._send(
                        HTTPStatus.OK, _json_bytes(build_workflow(runtime, db)),
                        "application/json; charset=utf-8",
                    )
                    return
                if parsed.path == "/api/v1/alert-channel":
                    from mova_fpl.ops.alerts import channel_report

                    self._send(
                        HTTPStatus.OK, _json_bytes(channel_report(runtime, db)),
                        "application/json; charset=utf-8",
                    )
                    return
                if parsed.path == "/api/v1/postgres-cutover-drills":
                    raw = parse_qs(parsed.query).get("limit", ["20"])[0]
                    limit = max(1, min(int(raw), 100))
                    self._send(
                        HTTPStatus.OK,
                        _json_bytes({"schema": "mova-postgres-cutover-drills-v1",
                                     "items": db.recent_jobs_by_type(
                                         "postgres_read_cutover_drill", limit
                                     ), "limit": limit}),
                        "application/json; charset=utf-8",
                    )
                    return
                routes = {
                    "/api/v1/status": None,
                    "/api/v1/safety": "safety_summary",
                    "/api/v1/strategy": "strategic_status",
                    "/api/v1/jobs": "job_runs",
                    "/api/v1/steps": "job_steps",
                    "/api/v1/audit": "audit_events",
                    "/api/v1/incidents": "incidents",
                    "/api/v1/health": "health_samples",
                    "/api/v1/snapshots": "source_snapshots",
                    "/api/v1/team-state": "team_state_snapshots",
                    "/api/v1/decisions": "decision_runs",
                    "/api/v1/decision-envelopes": "decision_envelopes",
                    "/api/v1/decision-candidates": "decision_candidates",
                    "/api/v1/decision-checks": "decision_validation_checks",
                    "/api/v1/deliberations": "decision_deliberations",
                    "/api/v1/deliberation-bindings": "decision_deliberation_bindings",
                    "/api/v1/deliberation-risks": "decision_deliberation_risks",
                    "/api/v1/execution-plans": "execution_plans",
                    "/api/v1/execution-preflight-checks": "execution_preflight_checks",
                    "/api/v1/execution-attempts": "execution_attempts",
                    "/api/v1/execution-attempt-events": "execution_attempt_events",
                    "/api/v1/browser-rehearsals": "browser_rehearsals",
                    "/api/v1/outbox": "outbox_events",
                    "/api/v1/research/runs": "research_runs",
                    "/api/v1/research/documents": "research_documents",
                    "/api/v1/research/signals": "research_signals",
                    "/api/v1/research/conflicts": "research_conflicts",
                    "/api/v1/change-proposal-evaluations": "change_proposal_evaluations",
                    "/api/v1/lessons": "lessons",
                    "/api/v1/budget-reservations": "agent_budget_reservations",
                    "/api/v1/budget-overrun-events": "agent_budget_overrun_events",
                    "/api/v1/agent-attempt-events": "agent_worker_attempt_events",
                    "/api/v1/gameweek-reviews": "gameweek_reviews",
                    "/api/v1/model-bundle-releases": "model_bundle_releases",
                    "/api/v1/model-bundle-release-events": "model_bundle_release_events",
                }
                if parsed.path not in routes:
                    self._send(HTTPStatus.NOT_FOUND, b'{"error":"not_found"}', "application/json")
                    return
                if routes[parsed.path] is None:
                    payload = build_status(runtime, db)
                elif routes[parsed.path] == "safety_summary":
                    payload = build_safety(runtime, db)
                elif routes[parsed.path] == "strategic_status":
                    payload = db.strategic_status()
                else:
                    raw = parse_qs(parsed.query).get("limit", ["50"])[0]
                    limit = max(1, min(int(raw), 500))
                    payload = {"items": db.recent(routes[parsed.path], limit), "limit": limit}
                self._send(HTTPStatus.OK, _json_bytes(payload), "application/json; charset=utf-8")
            except (ValueError, OSError) as exc:
                self._send(HTTPStatus.BAD_REQUEST,
                           _json_bytes({"error": type(exc).__name__, "detail": str(exc)}),
                           "application/json; charset=utf-8")
            except Exception as exc:  # no filtrar trazas internas al cliente
                LOG.exception("http_failure", extra={"event": "http_failure"})
                self._send(HTTPStatus.SERVICE_UNAVAILABLE,
                           _json_bytes({"error": "service_unavailable", "detail": type(exc).__name__}),
                           "application/json; charset=utf-8")

        def do_POST(self) -> None:  # noqa: N802
            self._send(HTTPStatus.METHOD_NOT_ALLOWED,
                       b'{"error":"read_only_control_plane"}', "application/json")

    return Handler


def serve(config: RuntimeConfig, db: OpsDB) -> None:
    db.quick_check()
    server = ThreadingHTTPServer((config.api_host, config.api_port), make_handler(db, config))
    LOG.info("api_started", extra={"event": "api_started", "detail": {
        "host": config.api_host, "port": config.api_port,
    }})
    server.serve_forever()
