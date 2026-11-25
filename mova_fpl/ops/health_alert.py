"""Alerta única de salud mínima (ADR-022); sustituye al watchdog sin crear incidentes.

Dispara solo si `fpl_official` lleva más de 6 h sin estar healthy o si el disco
libre cae bajo el gate de 20 GiB. Va a journal y al sink externo configurado, con
cooldown para no repetir. No abre incidentes P0/P1 ni bloquea la autoridad.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from typing import Callable

from mova_fpl.ops.alerts import configured_sink
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB

LOG = logging.getLogger("mova_fpl.ops.health_alert")
FPL_UNHEALTHY_SECONDS = 6 * 3600
COOLDOWN_SECONDS = 12 * 3600
EVENT_TYPE = "health_alert"


def assess(config: RuntimeConfig, *, collector_status: dict | None = None,
           disk_free: int | None = None) -> dict:
    reasons: list[str] = []
    if collector_status is None:
        try:
            from mova_fpl.ops.collector.store import CollectorStore

            collector_status = CollectorStore(config).status()
        except Exception:  # noqa: BLE001 - sin Postgres no hay señal de colector
            collector_status = {"sources": []}
    sources = {row["source_name"]: row for row in collector_status.get("sources") or ()}
    fpl = sources.get("fpl_official")
    if fpl is not None and fpl.get("health") != "healthy":
        age = fpl.get("age_seconds")
        if age is None or age > FPL_UNHEALTHY_SECONDS:
            reasons.append("fpl_official_unhealthy_over_6h")
    if disk_free is None:
        root = config.artifact_root if config.artifact_root.exists() else config.artifact_root.parent
        disk_free = shutil.disk_usage(root).free
    if disk_free < config.disk_gate_bytes:
        reasons.append("disk_below_20gib")
    return {"healthy": not reasons, "reasons": reasons, "disk_free_bytes": disk_free}


def run(config: RuntimeConfig, db: OpsDB, *, now: datetime | None = None,
        collector_status: dict | None = None, disk_free: int | None = None,
        sink: Callable[[dict], None] | None = None) -> dict:
    current = now or datetime.now(timezone.utc)
    result = assess(config, collector_status=collector_status, disk_free=disk_free)
    payload = {"schema": "mova-health-alert-v1", **result, "alerted": False}
    if result["healthy"]:
        return payload
    con = db.connect(readonly=True)
    try:
        last = con.execute(
            "SELECT occurred_at FROM audit_events WHERE event_type=? "
            "ORDER BY occurred_at DESC LIMIT 1", (EVENT_TYPE,),
        ).fetchone()
    finally:
        con.close()
    if last:
        elapsed = (current - datetime.fromisoformat(last[0])).total_seconds()
        if 0 <= elapsed < COOLDOWN_SECONDS:
            payload["suppressed"] = "cooldown"
            return payload
    title = "MOVA salud mínima: " + ", ".join(result["reasons"])
    event = {
        "outbox_id": f"health-{int(current.timestamp())}",
        "event_key": f"health_alert:{int(current.timestamp())}",
        "event_type": EVENT_TYPE, "severity": "P1", "attempts": 0,
        "created_at": current.isoformat(timespec="seconds"),
        "payload_json": json.dumps({"title": title, "reasons": result["reasons"]}),
    }
    LOG.warning("mova_health_alert", extra={"event": "mova_health_alert",
                                            "detail": {"reasons": result["reasons"]}})
    try:
        (sink or configured_sink(config))(event)
        payload["alerted"] = True
    except Exception as exc:  # noqa: BLE001 - la alerta nunca debe romper el colector
        payload["sink_error"] = type(exc).__name__
        payload["alerted"] = True  # journal ya recibió el aviso
    db.append_audit(EVENT_TYPE, actor="mova-collector", severity="warning",
                    payload={"reasons": result["reasons"],
                             "disk_free_bytes": result["disk_free_bytes"]})
    return payload
