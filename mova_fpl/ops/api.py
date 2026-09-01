"""API local de observabilidad, deliberadamente de solo lectura."""

from __future__ import annotations

import html
import json
import logging
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB
from mova_fpl.ops.operator import build_safety, build_status

LOG = logging.getLogger(__name__)


def _json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")


def _dashboard(cockpit: dict) -> bytes:
    esc = lambda value: html.escape(str(value if value is not None else "—"))
    gameweek = cockpit.get("gameweek") or {}
    authority = cockpit.get("authority") or {}
    quality = cockpit.get("quality") or {}
    economics = cockpit.get("economics") or {}
    gw_cost = economics.get("gameweek") or {}
    alerts = (cockpit.get("alerts") or {}).get("items") or []
    verdict = str(cockpit.get("verdict") or "attention_required")
    tone = "danger" if verdict == "critical" else "warning" if alerts else "ok"
    alert_rows = "".join(
        f'<div class="alert {"danger" if row.get("severity") in {"P0", "P1"} else "warning"}">'
        f'<strong>{esc(row.get("severity"))} · {esc(row.get("title"))}</strong>'
        f'<code>{esc(row.get("action"))}</code></div>' for row in alerts
    ) or '<div class="alert ok"><strong>Sin alertas accionables</strong></div>'
    functions = "".join(
        f'<tr><td><span class="dot {"on" if row.get("enabled") else "off"}"></span>'
        f'{esc(row.get("name"))}</td><td>{esc(row.get("status"))}</td>'
        f'<td><code>{esc(row.get("mode"))}</code></td></tr>'
        for row in cockpit.get("functions") or []
    )
    stages = "".join(
        f'<div class="stage"><span>{esc(row.get("name"))}</span>'
        f'<strong class="state-{esc(row.get("status"))}">{esc(row.get("status"))}</strong>'
        f'<small>{esc(row.get("outcome"))}</small></div>'
        for row in (cockpit.get("workflow") or {}).get("stages") or []
    )
    body = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<meta http-equiv="refresh" content="30"><title>MOVA · Cockpit</title>
<style>
:root {{ color-scheme:dark; font-family:Inter,ui-sans-serif,system-ui,sans-serif; background:#071019;color:#edf5ff }}
* {{ box-sizing:border-box }} body {{ max-width:1240px;margin:0 auto;padding:2rem 1.25rem 4rem }}
h1,h2 {{ margin:.2rem 0 }} h2 {{ font-size:1.05rem;margin-top:2rem }} .muted,small {{ color:#8fa2b8 }}
.hero {{ display:flex;justify-content:space-between;gap:1rem;align-items:flex-end;margin-bottom:1.4rem }}
.pill {{ padding:.45rem .75rem;border-radius:999px;font-weight:750;text-transform:uppercase;font-size:.76rem }}
.pill.ok {{ background:#103d31;color:#79efc2 }} .pill.warning {{ background:#493813;color:#ffd876 }} .pill.danger {{ background:#4d1821;color:#ff99a6 }}
.banner {{ border:1px solid #26384b;background:#0e1a27;border-radius:16px;padding:1rem 1.15rem;margin:1rem 0 }}
.banner.warning {{ border-color:#82631d }} .banner.danger {{ border-color:#a83948 }}
.grid {{ display:grid;grid-template-columns:repeat(auto-fit,minmax(205px,1fr));gap:.85rem;margin:1rem 0 }}
.card {{ background:#0e1a27;border:1px solid #26384b;border-radius:14px;padding:1rem;min-height:112px }}
.value {{ font-size:1.55rem;font-weight:760;margin:.35rem 0 }} .label {{ color:#8fa2b8;font-size:.82rem;text-transform:uppercase;letter-spacing:.06em }}
.alerts {{ display:grid;gap:.6rem }} .alert {{ display:flex;justify-content:space-between;gap:1rem;align-items:center;padding:.8rem 1rem;border-radius:10px;background:#10253a;border-left:4px solid #4e8ac8 }}
.alert.warning {{ border-color:#e2aa32 }} .alert.danger {{ border-color:#f05d6f }} .alert.ok {{ border-color:#35c99a }}
code {{ color:#8de6c6;font-size:.82rem }} table {{ width:100%;border-collapse:collapse;background:#0e1a27;border:1px solid #26384b;border-radius:12px;overflow:hidden }}
td,th {{ text-align:left;padding:.72rem;border-bottom:1px solid #26384b }} .dot {{ display:inline-block;width:.58rem;height:.58rem;border-radius:50%;margin-right:.55rem }} .dot.on {{ background:#35c99a }} .dot.off {{ background:#697b8e }}
.pipeline {{ display:grid;grid-template-columns:repeat(auto-fit,minmax(125px,1fr));gap:.55rem }} .stage {{ background:#0e1a27;border:1px solid #26384b;border-radius:10px;padding:.75rem;display:grid;gap:.25rem }}
.stage strong {{ font-size:.82rem }} .state-complete,.state-skipped_policy {{ color:#64ddb3 }} .state-degraded,.state-pending {{ color:#f1c75b }} .state-blocked {{ color:#ff7585 }}
.links {{ line-height:2 }} a {{ color:#82b7ff;text-decoration:none }} @media(max-width:700px) {{ .hero,.alert {{ align-items:flex-start;flex-direction:column }} }}
</style></head><body>
<header class="hero"><div><h1>MOVA Fantasy Fútbol</h1><div class="muted">Cockpit autónomo · solo lectura · refresca cada 30 s</div></div><span class="pill {tone}">{esc(verdict)}</span></header>
<section class="banner {tone}"><strong>{esc(cockpit.get('headline'))}</strong><div class="muted">Snapshot {esc(cockpit.get('generated_at'))} · revisión {esc((cockpit.get('runtime') or {}).get('git_sha'))}</div></section>
<div class="grid">
<div class="card"><div class="label">Jornada</div><div class="value">GW {esc(gameweek.get('gw'))}</div><div>{esc(gameweek.get('phase'))} · {esc(gameweek.get('readiness'))}</div></div>
<div class="card"><div class="label">Deadline UTC</div><div class="value">{esc(gameweek.get('deadline_at'))}</div><div>{esc(gameweek.get('seconds_to_deadline'))} segundos</div></div>
<div class="card"><div class="label">Autoridad</div><div class="value">{esc(authority.get('current_action_level'))}</div><div>writes {esc(authority.get('writes_enabled'))} · kill switch {esc(authority.get('kill_switch'))}</div></div>
<div class="card"><div class="label">Readiness</div><div class="value">{esc(quality.get('readiness'))}</div><div>elegible técnicamente {esc(authority.get('technical_eligible_level'))}</div></div>
<div class="card"><div class="label">Presupuesto GW</div><div class="value">{esc(gw_cost.get('committed_uses'))}/{esc(gw_cost.get('use_limit'))}</div><div>{esc(gw_cost.get('remaining_tokens'))} tokens restantes</div></div>
<div class="card"><div class="label">Incidentes críticos</div><div class="value">{esc((cockpit.get('alerts') or {}).get('critical_open'))}</div><div>outbox due {esc((cockpit.get('alerts') or {}).get('outbox_due'))}</div></div>
</div>
<h2>Alertas y acciones</h2><div class="alerts">{alert_rows}</div>
<h2>Ciclo agentic</h2><div class="pipeline">{stages}</div>
<h2>Funciones y activaciones</h2><table><thead><tr><th>Función</th><th>Estado</th><th>Modo</th></tr></thead><tbody>{functions}</tbody></table>
<h2>Diagnóstico</h2><div class="links"><a href="/api/v1/cockpit">cockpit JSON</a> · <a href="/api/v1/triage">triage JSON</a> · <a href="/api/v1/status">status</a> · <a href="/api/v1/readiness">readiness</a> · <a href="/api/v1/harness-scorecard">scorecard</a> · <a href="/api/v1/orchestration">workflow</a> · <a href="/api/v1/costs">costos</a> · <a href="/api/v1/incidents">incidentes</a></div>
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
