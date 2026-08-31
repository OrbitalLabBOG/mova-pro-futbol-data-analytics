"""Watchdog independiente y rehearsal hermético de recuperación."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from mova_fpl.ops.alerts import configured_sink, dispatch, journal_sink
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB

INCIDENT_TITLE = "Scheduler heartbeat unhealthy"
AGENT_QUEUE_INCIDENT_TITLE = "Agent queue integrity unhealthy"
MAX_REQUEST_BYTES = 1_048_576
REQUEST_ID = re.compile(r"(?:research|deliberation)_[0-9a-f]{32}")
ACTIVE_RESEARCH_STATUSES = {"queued", "running", "completed"}
ACTIVE_DELIBERATION_STATUSES = {"queued", "running"}
MAX_PERMIT_BYTES = 65_536


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


def assess_agent_queue(config: RuntimeConfig, db: OpsDB, *,
                       now: datetime | None = None,
                       orphan_grace_seconds: int = 60,
                       max_registered_age_seconds: int = 2100,
                       max_started_age_seconds: int = 900) -> dict:
    """Inspect the filesystem queue independently from the agent importer."""
    current = now or datetime.now(timezone.utc)
    inbox = config.research_root / "inbox"
    anomalies = []
    request_count = 0
    for path in sorted(inbox.glob("*.request.json")) if inbox.exists() else ():
        request_count += 1
        try:
            stat = path.lstat()
            age = max(0, int(current.timestamp() - stat.st_mtime))
            reason = None
            request_id = path.name.removesuffix(".request.json")
            kind = (
                "research" if request_id.startswith("research_") else
                "deliberation" if request_id.startswith("deliberation_") else None
            )
            if path.is_symlink() or not path.is_file():
                reason = "unsafe_request_path"
            elif not kind or not REQUEST_ID.fullmatch(request_id):
                reason = "invalid_request_name"
            elif stat.st_size > MAX_REQUEST_BYTES:
                reason = "request_too_large"
            else:
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    payload = None
                    reason = "invalid_request_json"
                expected_schema = (
                    "mova-research-request-v1" if kind == "research" else
                    "mova-decision-deliberation-request-v1"
                )
                identity_field = (
                    "research_run_id" if kind == "research" else "deliberation_id"
                )
                if payload is not None and (
                    not isinstance(payload, dict)
                    or payload.get("schema") != expected_schema
                    or payload.get(identity_field) != request_id
                ):
                    reason = "request_identity_mismatch"
            if reason is None:
                outbox = config.research_root / "outbox" / f"{request_id}.result.json"
                archive = config.research_root / "archive" / f"{request_id}.result.json"
                quarantine = (
                    config.research_root / "quarantine" / f"{request_id}.result.json"
                )
                run = (
                    db.research_run(request_id) if kind == "research"
                    else db.decision_deliberation(request_id)
                )
                active_statuses = (
                    ACTIVE_RESEARCH_STATUSES if kind == "research"
                    else ACTIVE_DELIBERATION_STATUSES
                )
                if quarantine.is_file():
                    reason = "quarantined_result_tombstone"
                elif archive.is_file():
                    reason = "archived_result_with_live_request"
                elif not run and age >= orphan_grace_seconds:
                    reason = "unregistered_request"
                elif run and run.get("status") not in active_statuses:
                    reason = f"terminal_status:{run.get('status')}"
                elif age >= max_registered_age_seconds and not outbox.is_file():
                    reason = "registered_request_stale"
            if reason:
                anomalies.append({
                    "request_id": request_id[:80], "reason": reason,
                    "age_seconds": age,
                })
        except OSError as exc:
            anomalies.append({
                "request_id": path.name[:80], "reason": type(exc).__name__,
                "age_seconds": None,
            })

    permits = config.research_root / "permits"
    authorization_rows = db.agent_attempt_authorizations()
    referenced_paths = {str(Path(row["permit_path"]).absolute()) for row in authorization_rows}
    authorization_counts: dict[str, int] = {}
    permit_count = 0
    for row in authorization_rows:
        status = str(row["status"])
        authorization_counts[status] = authorization_counts.get(status, 0) + 1
        if status not in {"preparing", "authorized", "started"}:
            continue
        authorization_id = str(row["authorization_id"])
        created = datetime.fromisoformat(
            str(row["created_at"]).replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        age = max(0, int((current - created).total_seconds()))
        expires = datetime.fromisoformat(
            str(row["expires_at"]).replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        reason = None
        path = Path(row["permit_path"])
        expected_name = f"{row['subject_id']}.{authorization_id}.permit.json"
        if status == "preparing":
            if age >= orphan_grace_seconds:
                reason = "authorization_preparing_stale"
        elif status == "authorized" and expires <= current:
            reason = "authorization_expired_unreconciled"
        else:
            try:
                if (path.name != expected_name or path.is_symlink()
                        or not path.is_file()
                        or path.absolute().parent != permits.absolute()):
                    reason = "authorization_permit_missing_or_unsafe"
                elif path.stat().st_size > MAX_PERMIT_BYTES:
                    reason = "authorization_permit_too_large"
                else:
                    raw = path.read_bytes()
                    digest = hashlib.sha256(raw).hexdigest()
                    if digest != row["permit_sha256"]:
                        reason = "authorization_permit_hash_mismatch"
            except OSError:
                reason = "authorization_permit_unreadable"
            if reason is None:
                try:
                    payload = json.loads(raw)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    payload = None
                if not isinstance(payload, dict) or any((
                    payload.get("schema") != "mova-agent-attempt-permit-v1",
                    payload.get("authorization_id") != authorization_id,
                    payload.get("subject_type") != row["subject_type"],
                    payload.get("subject_id") != row["subject_id"],
                    payload.get("request_sha256") != row["request_sha256"],
                    payload.get("attempt_number") != int(row["attempt_number"]),
                    payload.get("expires_at") != row["expires_at"],
                )):
                    reason = "authorization_permit_identity_mismatch"
        if reason is None and status == "started":
            if not row["started_at"] or not row["attempt_id"]:
                reason = "authorization_started_identity_missing"
            else:
                started = datetime.fromisoformat(
                    str(row["started_at"]).replace("Z", "+00:00")
                ).astimezone(timezone.utc)
                started_age = max(0, int((current - started).total_seconds()))
                if started_age >= max_started_age_seconds:
                    reason = "authorization_started_stale"
                    age = started_age
        if reason:
            anomalies.append({
                "authorization_id": authorization_id,
                "subject_id": str(row["subject_id"])[:80],
                "reason": reason, "age_seconds": age,
            })

    for path in sorted(permits.glob("*.permit.json")) if permits.exists() else ():
        permit_count += 1
        try:
            stat = path.lstat()
            age = max(0, int(current.timestamp() - stat.st_mtime))
            if str(path.absolute()) not in referenced_paths and age >= orphan_grace_seconds:
                anomalies.append({
                    "authorization_id": None, "subject_id": path.name[:80],
                    "reason": "orphan_permit", "age_seconds": age,
                })
        except OSError as exc:
            anomalies.append({
                "authorization_id": None, "subject_id": path.name[:80],
                "reason": type(exc).__name__, "age_seconds": None,
            })
    return {
        "healthy": not anomalies, "present": inbox.exists() or permits.exists(),
        "requests": request_count, "permits": permit_count,
        "authorizations": authorization_counts,
        "anomalies": anomalies[:20], "anomaly_count": len(anomalies),
        "orphan_grace_seconds": orphan_grace_seconds,
        "max_registered_age_seconds": max_registered_age_seconds,
        "max_started_age_seconds": max_started_age_seconds,
    }


def agent_queue_prometheus(state: dict) -> str:
    return "\n".join((
        "# HELP mova_agent_queue_healthy Whether the isolated agent queue has no anomaly.",
        "# TYPE mova_agent_queue_healthy gauge",
        f"mova_agent_queue_healthy {1 if state.get('healthy') else 0}",
        "# HELP mova_agent_queue_requests Request files currently visible to the worker.",
        "# TYPE mova_agent_queue_requests gauge",
        f"mova_agent_queue_requests {int(state.get('requests') or 0)}",
        "# HELP mova_agent_queue_permits Permit files currently visible to the worker.",
        "# TYPE mova_agent_queue_permits gauge",
        f"mova_agent_queue_permits {int(state.get('permits') or 0)}",
        "# HELP mova_agent_queue_anomalies Requests that violate queue lifecycle invariants.",
        "# TYPE mova_agent_queue_anomalies gauge",
        f"mova_agent_queue_anomalies {int(state.get('anomaly_count') or 0)}",
        "",
    ))


def run(db: OpsDB, *, max_age_seconds: int = 1200,
        now: datetime | None = None,
        sink: Callable[[dict], None] | None = None,
        config: RuntimeConfig | None = None) -> dict:
    effective_config = config or RuntimeConfig()
    state = assess(db, max_age_seconds=max_age_seconds, now=now)
    expired_authorizations = db.expire_agent_attempt_authorizations(
        now=now or datetime.now(timezone.utc)
    )
    agent_queue = assess_agent_queue(effective_config, db, now=now)
    if state["healthy"]:
        scheduler_resolved = db.resolve_incidents(
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
        scheduler_resolved = 0
    if agent_queue["healthy"]:
        queue_resolved = db.resolve_incidents(
            AGENT_QUEUE_INCIDENT_TITLE, resolution="agent queue integrity recovered",
            actor="mova-watchdog",
        )
    else:
        db.open_incident_once(
            "P1", AGENT_QUEUE_INCIDENT_TITLE,
            detail={
                "anomaly_count": agent_queue["anomaly_count"],
                "anomalies": agent_queue["anomalies"],
            },
        )
        queue_resolved = 0
    alerts = dispatch(db, sink=sink or configured_sink(effective_config))
    outbox = db.outbox_status()
    dead = sum((outbox["counts"].get("dead") or {}).values())
    operational_status = (
        "down" if not state["healthy"] else
        "degraded" if not agent_queue["healthy"] or alerts["failed"] or dead else "ok"
    )
    return {
        "schema": "mova-watchdog-v2",
        "status": operational_status,
        "reason": state["reason"] or (
            None if agent_queue["healthy"] else "agent_queue_unhealthy"
        ),
        "tick_age_seconds": state["tick_age_seconds"],
        "latest_tick_status": state["latest_tick_status"],
        "incidents_resolved": scheduler_resolved + queue_resolved,
        "resolved_by_domain": {
            "scheduler": scheduler_resolved, "agent_queue": queue_resolved,
        },
        "agent_queue": agent_queue,
        "expired_authorizations": expired_authorizations,
        "alerts": alerts,
        "outbox_dead": dead,
    }


def resilience_drill() -> dict:
    """Prueba la ruta P0 completa sobre una DB efímera, sin tocar el runtime."""
    delivered: list[str] = []
    with TemporaryDirectory(prefix="mova-resilience-") as temporary:
        root = Path(temporary)
        db = OpsDB(root / "ops.db", enforce_version=False)
        db.migrate()
        config = RuntimeConfig(research_root=root / "research")
        current = datetime.now(timezone.utc)
        first = run(
            db, now=current,
            sink=lambda event: delivered.append(str(event["event_key"])),
            config=config,
        )
        duplicate = run(
            db, now=current + timedelta(seconds=1),
            sink=lambda event: delivered.append(str(event["event_key"])),
            config=config,
        )
        job_id, _ = db.start_job("tick", "drill:recovered-tick", "corr_drill")
        db.finish_job(job_id, "completed")
        recovered = run(
            db, now=current + timedelta(seconds=2),
            sink=lambda event: delivered.append(str(event["event_key"])),
            config=config,
        )
        orphan_id = "deliberation_" + "1" * 32
        orphan = config.research_root / "inbox" / f"{orphan_id}.request.json"
        orphan.parent.mkdir(parents=True, exist_ok=True)
        orphan.write_text(json.dumps({
            "schema": "mova-decision-deliberation-request-v1",
            "deliberation_id": orphan_id,
        }), encoding="utf-8")
        old = current.timestamp() - 120
        os.utime(orphan, (old, old))
        queue_failure = run(
            db, now=current + timedelta(seconds=3),
            sink=lambda event: delivered.append(str(event["event_key"])),
            config=config,
        )
        queue_duplicate = run(
            db, now=current + timedelta(seconds=4),
            sink=lambda event: delivered.append(str(event["event_key"])),
            config=config,
        )
        orphan.unlink()
        queue_recovered = run(
            db, now=current + timedelta(seconds=5),
            sink=lambda event: delivered.append(str(event["event_key"])),
            config=config,
        )
        with db.connect(readonly=True) as con:
            incident_rows = int(con.execute(
                "SELECT COUNT(*) FROM incidents WHERE title=?", (INCIDENT_TITLE,),
            ).fetchone()[0])
            open_rows = int(con.execute(
                "SELECT COUNT(*) FROM incidents WHERE title=? AND status!='resolved'",
                (INCIDENT_TITLE,),
            ).fetchone()[0])
            queue_incident_rows = int(con.execute(
                "SELECT COUNT(*) FROM incidents WHERE title=?",
                (AGENT_QUEUE_INCIDENT_TITLE,),
            ).fetchone()[0])
            queue_open_rows = int(con.execute(
                "SELECT COUNT(*) FROM incidents WHERE title=? AND status!='resolved'",
                (AGENT_QUEUE_INCIDENT_TITLE,),
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
        "orphan_request_opens_p1": (
            queue_failure["status"] == "degraded"
            and queue_failure["reason"] == "agent_queue_unhealthy"
        ),
        "queue_alert_delivered": queue_failure["alerts"]["delivered"] == 1,
        "queue_incident_deduplicated": (
            queue_duplicate["alerts"]["claimed"] == 0 and queue_incident_rows == 1
        ),
        "queue_recovery_resolves_incident": (
            queue_recovered["status"] == "ok" and queue_open_rows == 0
        ),
    }
    return {
        "schema": "mova-resilience-drill-v1",
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
        "delivered_event_keys": delivered,
        "runtime_mutated": False,
    }
