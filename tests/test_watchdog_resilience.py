from __future__ import annotations

from datetime import datetime, timedelta, timezone

from mova_fpl.ops.db import OpsDB
from mova_fpl.ops.watchdog import INCIDENT_TITLE, resilience_drill, run


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
