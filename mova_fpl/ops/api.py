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

LOG = logging.getLogger(__name__)


def _json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")


def _dashboard(status: dict) -> bytes:
    cycle = status.get("cycle") or {}
    tick = status.get("latest_tick") or {}
    controls = status.get("controls") or {}
    team_state = status.get("latest_team_state") or {}
    control_rows = "".join(
        f"<tr><td>{html.escape(key)}</td><td><code>{html.escape(json.dumps(item['value']))}</code></td>"
        f"<td>{html.escape(item['actor'])}</td></tr>"
        for key, item in controls.items()
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
<div class="card"><div class="muted">Incidentes abiertos</div><div class="value">{sum(status.get('open_incidents',{}).values())}</div><div>{html.escape(json.dumps(status.get('open_incidents',{})))}</div></div>
<div class="card"><div class="muted">Alertas pendientes</div><div class="value">{status.get('outbox_pending',0)}</div><div>SQLite {html.escape(status.get('sqlite_version',''))}</div></div>
<div class="card"><div class="muted">Estado privado</div><div class="value">{html.escape(str(team_state.get('quality_status','sin datos')))}</div><div>{html.escape(str(team_state.get('observed_at','')))} · FT {html.escape(str(team_state.get('free_transfers','—')))}</div></div>
</div>
<h2>Controles efectivos</h2><table><thead><tr><th>Control</th><th>Valor</th><th>Actor</th></tr></thead><tbody>{control_rows}</tbody></table>
<p><a href="/api/v1/status">status JSON</a> · <a href="/metrics">métricas</a> · <a href="/api/v1/audit">auditoría</a> · <a href="/api/v1/jobs">jobs</a></p>
</body></html>"""
    return body.encode("utf-8")


def make_handler(db: OpsDB):
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
                    self._send(HTTPStatus.OK, db.prometheus().encode(),
                               "text/plain; version=0.0.4; charset=utf-8")
                    return
                if parsed.path in {"/", "/dashboard"}:
                    self._send(HTTPStatus.OK, _dashboard(db.status()), "text/html; charset=utf-8")
                    return
                routes = {
                    "/api/v1/status": None,
                    "/api/v1/jobs": "job_runs",
                    "/api/v1/audit": "audit_events",
                    "/api/v1/incidents": "incidents",
                    "/api/v1/health": "health_samples",
                    "/api/v1/snapshots": "source_snapshots",
                    "/api/v1/team-state": "team_state_snapshots",
                    "/api/v1/decisions": "decision_runs",
                    "/api/v1/outbox": "outbox_events",
                }
                if parsed.path not in routes:
                    self._send(HTTPStatus.NOT_FOUND, b'{"error":"not_found"}', "application/json")
                    return
                if routes[parsed.path] is None:
                    payload = db.status()
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
    server = ThreadingHTTPServer((config.api_host, config.api_port), make_handler(db))
    LOG.info("api_started", extra={"event": "api_started", "detail": {
        "host": config.api_host, "port": config.api_port,
    }})
    server.serve_forever()
