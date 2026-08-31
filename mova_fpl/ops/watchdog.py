"""Watchdog independiente y rehearsal hermético de recuperación."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from mova_fpl.ops.alerts import configured_sink, dispatch, journal_sink
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB

INCIDENT_TITLE = "Scheduler heartbeat unhealthy"


def assess(db: OpsDB, *, max_age_seconds: int = 1200,
           now: datetime | None = None) -> dict:
    current = now or datetime.now(timezone.utc)
    db.quick_check()
    tick = (db.status().get("latest_tick") or {})
    finished = tick.get("finished_at")
    if not finished:
        return {"healthy": False, "reason": "no_finished_tick",
                "tick_age_seconds": None, "latest_tick_status": tick.get("status")}
    observed = datetime.fromisoformat(str(finished).replace("Z", "+00:00"))
    age = max(0, int((current - observed).total_seconds()))
    healthy = age <= max_age_seconds and tick.get("status") in {"completed", "degraded"}
    return {
        "healthy": healthy,
        "reason": None if healthy else (
            "tick_stale" if age > max_age_seconds else "latest_tick_failed"
        ),
        "tick_age_seconds": age,
        "latest_tick_status": tick.get("status"),
    }


def run(db: OpsDB, *, max_age_seconds: int = 1200,
        now: datetime | None = None,
        sink: Callable[[dict], None] | None = None,
        config: RuntimeConfig | None = None) -> dict:
    state = assess(db, max_age_seconds=max_age_seconds, now=now)
    if state["healthy"]:
        resolved = db.resolve_incidents(
            INCIDENT_TITLE, resolution="scheduler heartbeat recovered",
            actor="mova-watchdog",
        )
    else:
        db.open_incident_once(
            "P0", INCIDENT_TITLE,
            detail={key: state[key] for key in (
                "reason", "tick_age_seconds", "latest_tick_status"
            )},
        )
        resolved = 0
    alerts = dispatch(db, sink=sink or configured_sink(config or RuntimeConfig()))
    outbox = db.outbox_status()
    dead = sum((outbox["counts"].get("dead") or {}).values())
    operational_status = (
        "down" if not state["healthy"] else
        "degraded" if alerts["failed"] or dead else "ok"
    )
    return {
        "schema": "mova-watchdog-v2",
        "status": operational_status,
        "reason": state["reason"],
        "tick_age_seconds": state["tick_age_seconds"],
        "latest_tick_status": state["latest_tick_status"],
        "incidents_resolved": resolved,
        "alerts": alerts,
        "outbox_dead": dead,
    }


def resilience_drill() -> dict:
    """Prueba la ruta P0 completa sobre una DB efímera, sin tocar el runtime."""
    delivered: list[str] = []
    with TemporaryDirectory(prefix="mova-resilience-") as temporary:
        db = OpsDB(Path(temporary) / "ops.db", enforce_version=False)
        db.migrate()
        current = datetime.now(timezone.utc)
        first = run(
            db, now=current,
            sink=lambda event: delivered.append(str(event["event_key"])),
        )
        duplicate = run(
            db, now=current + timedelta(seconds=1),
            sink=lambda event: delivered.append(str(event["event_key"])),
        )
        job_id, _ = db.start_job("tick", "drill:recovered-tick", "corr_drill")
        db.finish_job(job_id, "completed")
        recovered = run(
            db, now=current + timedelta(seconds=2),
            sink=lambda event: delivered.append(str(event["event_key"])),
        )
        with db.connect(readonly=True) as con:
            incident_rows = int(con.execute(
                "SELECT COUNT(*) FROM incidents WHERE title=?", (INCIDENT_TITLE,),
            ).fetchone()[0])
            open_rows = int(con.execute(
                "SELECT COUNT(*) FROM incidents WHERE title=? AND status!='resolved'",
                (INCIDENT_TITLE,),
            ).fetchone()[0])
            audit_events = {str(row[0]) for row in con.execute(
                "SELECT event_type FROM audit_events"
            )}
    checks = {
        "missing_tick_opens_p0": first["status"] == "down",
        "p0_delivered": first["alerts"]["delivered"] == 1,
        "duplicate_is_deduplicated": duplicate["alerts"]["claimed"] == 0,
        "single_incident": incident_rows == 1,
        "recovery_resolves_incident": recovered["status"] == "ok" and open_rows == 0,
        "audit_continuity": {"alert_delivery_succeeded", "incident_resolved"} <= audit_events,
    }
    return {
        "schema": "mova-resilience-drill-v1",
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
        "delivered_event_keys": delivered,
        "runtime_mutated": False,
    }
