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
from mova_fpl.ops.operator import build_status

LOG = logging.getLogger(__name__)


def _json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")


def _dashboard(status: dict) -> bytes:
    cycle = status.get("gameweek") or {}
    operations = status.get("operations") or {}
    tick = operations.get("latest_tick") or {}
    controls = (status.get("runtime") or {}).get("controls") or {}
    team_state = (status.get("data") or {}).get("team_state") or {}
    scorecard = ((status.get("analytics") or {}).get("latest_scorecards") or [{}])[0]
    control_rows = "".join(
        f"<tr><td>{html.escape(key)}</td><td><code>{html.escape(json.dumps(value))}</code></td></tr>"
        for key, value in controls.items()
    )
    body = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<meta http-equiv="refresh" content="30"><title>MOVA FPL Control Plane</title>
<style>
:root {{ color-scheme: dark; font-family: Inter,system-ui,sans-serif; background:#0c111b; color:#e8edf6 }}
body {{ max-width:1100px; margin:3rem auto; padding:0 1.25rem }}
h1 {{ margin-bottom:.25rem }} .muted {{ color:#98a6ba }} .grid {{ display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:1rem;margin:2rem 0 }}
.card {{ background:#151d2a;border:1px solid #28344a;border-radius:12px;padding:1rem }}
.value {{ font-size:1.55rem;font-weight:700;margin-top:.4rem }} table {{ width:100%;border-collapse:collapse;background:#151d2a }}
td,th {{ text-align:left;padding:.75rem;border-bottom:1px solid #28344a }} code {{ color:#7fe0c3 }}
a {{ color:#72a7ff }}
</style></head><body>
<h1>MOVA Fantasy Fútbol</h1><div class="muted">Control plane local · solo lectura · refresca cada 30 s</div>
<div class="grid">
<div class="card"><div class="muted">Jornada</div><div class="value">GW {html.escape(str(cycle.get('gw','—')))}</div><div>{html.escape(str(cycle.get('phase','sin ciclo')))}</div></div>
<div class="card"><div class="muted">Último tick</div><div class="value">{html.escape(str(tick.get('status','sin datos')))}</div><div>{html.escape(str(tick.get('started_at','')))}</div></div>
<div class="card"><div class="muted">Incidentes abiertos</div><div class="value">{len(operations.get('open_incidents',[]))}</div><div>{html.escape(status.get('overall_status','unknown'))}</div></div>
<div class="card"><div class="muted">Alertas pendientes</div><div class="value">{operations.get('outbox_pending',0)}</div><div>SQLite {html.escape(str((status.get('runtime') or {}).get('sqlite_version','')))}</div></div>
<div class="card"><div class="muted">Estado privado</div><div class="value">{html.escape(str(team_state.get('quality','sin datos')))}</div><div>{html.escape(str(team_state.get('observed_at','')))} · FT {html.escape(str(team_state.get('free_transfers','—')))}</div></div>
<div class="card"><div class="muted">Drift del modelo</div><div class="value">{html.escape(str(scorecard.get('drift_status','sin scorecard')))}</div><div>GW {html.escape(str(scorecard.get('gw','—')))} · {html.escape(str(scorecard.get('variant','')))}</div></div>
</div>
<h2>Controles efectivos</h2><table><thead><tr><th>Control</th><th>Valor</th></tr></thead><tbody>{control_rows}</tbody></table>
<p><a href="/api/v1/status">status JSON</a> · <a href="/api/v1/analytics">analytics</a> · <a href="/api/v1/strategy">strategy</a> · <a href="/api/v1/improvement">learning</a> · <a href="/api/v1/costs">costos</a> · <a href="/metrics">métricas</a> · <a href="/api/v1/audit">auditoría</a> · <a href="/api/v1/jobs">jobs</a> · <a href="/api/v1/steps">steps</a></p>
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
                    metrics += db.cost_prometheus(
                        runtime.agent_budget_policy(), season=runtime.season
                    )
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
                    self._send(HTTPStatus.OK, metrics.encode(),
                               "text/plain; version=0.0.4; charset=utf-8")
                    return
                if parsed.path in {"/", "/dashboard"}:
                    self._send(HTTPStatus.OK, _dashboard(build_status(runtime, db)),
                               "text/html; charset=utf-8")
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
                routes = {
                    "/api/v1/status": None,
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
                    "/api/v1/deliberation-risks": "decision_deliberation_risks",
                    "/api/v1/execution-plans": "execution_plans",
                    "/api/v1/execution-preflight-checks": "execution_preflight_checks",
                    "/api/v1/execution-attempts": "execution_attempts",
                    "/api/v1/execution-attempt-events": "execution_attempt_events",
                    "/api/v1/outbox": "outbox_events",
                    "/api/v1/research/runs": "research_runs",
                    "/api/v1/research/documents": "research_documents",
                    "/api/v1/research/signals": "research_signals",
                    "/api/v1/research/conflicts": "research_conflicts",
                    "/api/v1/change-proposal-evaluations": "change_proposal_evaluations",
                    "/api/v1/lessons": "lessons",
                    "/api/v1/budget-reservations": "agent_budget_reservations",
                }
                if parsed.path not in routes:
                    self._send(HTTPStatus.NOT_FOUND, b'{"error":"not_found"}', "application/json")
                    return
                if routes[parsed.path] is None:
                    payload = build_status(runtime, db)
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
