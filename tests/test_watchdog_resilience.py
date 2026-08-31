from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB
from mova_fpl.ops.watchdog import (
    AGENT_QUEUE_INCIDENT_TITLE,
    INCIDENT_TITLE,
    assess_agent_queue,
    resilience_drill,
    run,
)


def test_watchdog_opens_single_p0_delivers_and_resolves(tmp_path):
    db = OpsDB(tmp_path / "ops.db", enforce_version=False)
    db.migrate()
    delivered = []
    now = datetime.now(timezone.utc)

    first = run(db, now=now, sink=lambda event: delivered.append(event["event_key"]))
    duplicate = run(
        db, now=now + timedelta(seconds=1),
        sink=lambda event: delivered.append(event["event_key"]),
    )
    assert first["status"] == "down"
    assert first["reason"] == "no_finished_tick"
    assert first["alerts"]["delivered"] == 1
    assert duplicate["alerts"]["claimed"] == 0

    job_id, _ = db.start_job("tick", "tick:recovery", "corr_recovery")
    db.finish_job(job_id, "completed")
    recovered = run(
        db, now=now + timedelta(seconds=2),
        sink=lambda event: delivered.append(event["event_key"]),
    )
    assert recovered["status"] == "ok"
    assert recovered["incidents_resolved"] == 1
    with db.connect(readonly=True) as con:
        rows = con.execute(
            "SELECT severity,status FROM incidents WHERE title=?", (INCIDENT_TITLE,),
        ).fetchall()
    assert [(row["severity"], row["status"]) for row in rows] == [("P0", "resolved")]
    assert len(delivered) == 1


def test_watchdog_marks_stale_completed_tick_as_down(tmp_path):
    db = OpsDB(tmp_path / "ops.db", enforce_version=False)
    db.migrate()
    job_id, _ = db.start_job("tick", "tick:stale", "corr_stale")
    db.finish_job(job_id, "completed")
    result = run(
        db, now=datetime.now(timezone.utc) + timedelta(hours=1),
        max_age_seconds=1200, sink=lambda _event: None,
    )
    assert result["status"] == "down"
    assert result["reason"] == "tick_stale"


def test_watchdog_is_degraded_when_alert_delivery_dies(tmp_path):
    db = OpsDB(tmp_path / "ops.db", enforce_version=False)
    db.migrate()
    job_id, _ = db.start_job("tick", "tick:healthy", "corr_healthy")
    db.finish_job(job_id, "completed")
    db.open_incident("P1", "delivery fixture")

    result = run(
        db, sink=lambda _event: (_ for _ in ()).throw(RuntimeError("sink down")),
    )
    assert result["status"] == "degraded"
    assert result["alerts"]["failed"] == 1


def test_resilience_drill_is_hermetic_and_complete():
    result = resilience_drill()
    assert result["status"] == "pass"
    assert result["runtime_mutated"] is False
    assert all(result["checks"].values())


def test_resilience_status_is_machine_readable(tmp_path):
    db = OpsDB(tmp_path / "ops.db", enforce_version=False)
    db.migrate()
    assert db.resilience_drill_status() == {"status": "missing", "checks": 0, "passed": 0}
    job_id, _ = db.start_job("resilience_drill", "drill:status", "corr_status")
    db.finish_job(job_id, "completed", output_sha256="a" * 64,
                  metrics={"checks": 6, "passed": 6})
    status = db.resilience_drill_status()
    assert status["job_id"] == job_id
    assert status["status"] == "completed"
    assert status["checks"] == status["passed"] == 6


def test_watchdog_detects_deduplicates_and_resolves_orphan_agent_request(tmp_path):
    db = OpsDB(tmp_path / "ops.db", enforce_version=False)
    db.migrate()
    job_id, _ = db.start_job("tick", "tick:queue-health", "corr_queue_health")
    db.finish_job(job_id, "completed")
    config = RuntimeConfig(research_root=tmp_path / "research")
    request_id = "deliberation_" + "4" * 32
    request = config.research_root / "inbox" / f"{request_id}.request.json"
    request.parent.mkdir(parents=True)
    request.write_text(json.dumps({
        "schema": "mova-decision-deliberation-request-v1",
        "deliberation_id": request_id,
    }), encoding="utf-8")
    old = datetime.now(timezone.utc).timestamp() - 120
    os.utime(request, (old, old))
    delivered = []

    first = run(db, config=config, sink=lambda event: delivered.append(event["event_key"]))
    duplicate = run(
        db, config=config, sink=lambda event: delivered.append(event["event_key"])
    )
    request.unlink()
    recovered = run(
        db, config=config, sink=lambda event: delivered.append(event["event_key"])
    )

    assert first["status"] == "degraded"
    assert first["reason"] == "agent_queue_unhealthy"
    assert first["agent_queue"]["anomalies"][0]["reason"] == "unregistered_request"
    assert first["alerts"]["delivered"] == 1
    assert duplicate["alerts"]["claimed"] == 0
    assert recovered["status"] == "ok"
    assert recovered["resolved_by_domain"]["agent_queue"] == 1
    with db.connect(readonly=True) as con:
        rows = con.execute(
            "SELECT severity,status FROM incidents WHERE title=?",
            (AGENT_QUEUE_INCIDENT_TITLE,),
        ).fetchall()
    assert [(row["severity"], row["status"]) for row in rows] == [("P1", "resolved")]
    assert len(delivered) == 1


def test_agent_queue_allows_fresh_enqueue_but_rejects_quarantine_tombstone(tmp_path):
    db = OpsDB(tmp_path / "ops.db", enforce_version=False)
    db.migrate()
    config = RuntimeConfig(research_root=tmp_path / "research")
    request_id = "deliberation_" + "5" * 32
    request = config.research_root / "inbox" / f"{request_id}.request.json"
    request.parent.mkdir(parents=True)
    request.write_text(json.dumps({
        "schema": "mova-decision-deliberation-request-v1",
        "deliberation_id": request_id,
    }), encoding="utf-8")

    fresh = assess_agent_queue(config, db)
    tombstone = config.research_root / "quarantine" / f"{request_id}.result.json"
    tombstone.parent.mkdir(parents=True)
    tombstone.write_text("{}\n", encoding="utf-8")
    rejected = assess_agent_queue(config, db)

    assert fresh["healthy"] is True
    assert rejected["healthy"] is False
    assert rejected["anomalies"][0]["reason"] == "quarantined_result_tombstone"
