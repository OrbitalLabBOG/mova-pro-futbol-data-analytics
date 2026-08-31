from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

from mova_fpl.ops.agent_attempts import AgentAttemptService
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB, sha256_json
from mova_fpl.ops.watchdog import (
    AGENT_QUEUE_INCIDENT_TITLE,
    INCIDENT_TITLE,
    assess_agent_queue,
    resilience_drill,
    run,
)


def _runtime_with_authorization(tmp_path):
    config = RuntimeConfig(
        ops_db=tmp_path / "ops.db", research_root=tmp_path / "research",
        sqlite_min_version="0.0.0",
    )
    db = OpsDB(config.ops_db, enforce_version=False)
    db.migrate()
    cycle_id = db.upsert_cycle(
        "2026-27", 3, "2026-09-04T17:30:00+00:00", phase="preflight"
    )
    with db.transaction() as con:
        con.execute(
            """INSERT INTO cycle_manifests(
            manifest_id,cycle_id,revision,as_of_at,deadline_at,phase,team_state_id,plan_id,
            source_manifest_json,analytics_manifest_json,research_summary_json,artifact_path,
            content_sha256,created_at) VALUES(
            'manifest_watchdog_auth',?,1,'2026-08-30T12:00:00+00:00',
            '2026-09-04T17:30:00+00:00','preflight',NULL,NULL,'[]','{}','{}',
            'manifest.json',?, '2026-08-30T12:00:00+00:00')""",
            (cycle_id, "a" * 64),
        )
    run_id = "research_" + "c" * 32
    request = {
        "schema": "mova-research-request-v1", "research_run_id": run_id,
        "cycle_id": cycle_id, "fixture": True,
    }
    request_sha = sha256_json(request)
    request["request_sha256"] = request_sha
    request_path = config.research_root / "inbox" / f"{run_id}.request.json"
    request_path.parent.mkdir(parents=True)
    request_path.write_text(json.dumps(request) + "\n", encoding="utf-8")
    db.queue_research_run({
        "research_run_id": run_id, "cycle_id": cycle_id,
        "manifest_id": "manifest_watchdog_auth", "provider": "fixture",
        "request_path": str(request_path), "request_sha256": request_sha,
        "budget_policy": {"reservation_tokens": 100, "job_tokens": 200,
                          "gw_tokens": 300, "month_tokens": 600,
                          "gw_uses": 3, "month_uses": 6},
    })
    return config, db, run_id, request_sha


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


def test_watchdog_expires_unused_authorization_once_without_false_incident(tmp_path):
    config, db, _, _ = _runtime_with_authorization(tmp_path)
    base = datetime.now(timezone.utc)
    permit = AgentAttemptService(config, db).authorize_next(now=base)
    assert permit["status"] == "authorized"
    job_id, _ = db.start_job("tick", "tick:permit-expiry", "corr_permit_expiry")
    db.finish_job(job_id, "completed")

    first = run(db, config=config, now=base + timedelta(seconds=601),
                sink=lambda _event: None)
    replay = run(db, config=config, now=base + timedelta(seconds=602),
                 sink=lambda _event: None)

    assert first["status"] == "ok"
    assert [item["authorization_id"] for item in first["expired_authorizations"]] == [
        permit["authorization_id"]
    ]
    assert replay["expired_authorizations"] == []
    assert first["agent_queue"]["authorizations"]["expired"] == 1
    with db.connect(readonly=True) as con:
        assert con.execute(
            "SELECT COUNT(*) FROM audit_events "
            "WHERE event_type='agent_attempt_authorization_expired'"
        ).fetchone()[0] == 1


def test_watchdog_detects_tampered_authorization_permit_and_opens_p1(tmp_path):
    config, db, _, _ = _runtime_with_authorization(tmp_path)
    base = datetime.now(timezone.utc)
    permit = AgentAttemptService(config, db).authorize_next(now=base)
    permit_path = config.research_root / "permits" / (
        f"{permit['subject_id']}.{permit['authorization_id']}.permit.json"
    )
    permit_path.write_text(permit_path.read_text(encoding="utf-8") + " ",
                           encoding="utf-8")
    job_id, _ = db.start_job("tick", "tick:permit-tamper", "corr_permit_tamper")
    db.finish_job(job_id, "completed")

    result = run(db, config=config, now=base + timedelta(seconds=1),
                 sink=lambda _event: None)

    assert result["status"] == "degraded"
    assert result["reason"] == "agent_queue_unhealthy"
    assert result["agent_queue"]["anomalies"][0]["reason"] == (
        "authorization_permit_hash_mismatch"
    )
    with db.connect(readonly=True) as con:
        incident = con.execute(
            "SELECT severity,status FROM incidents WHERE title=?",
            (AGENT_QUEUE_INCIDENT_TITLE,),
        ).fetchone()
    assert dict(incident) == {"severity": "P1", "status": "open"}


def test_watchdog_detects_started_authorization_without_finish(tmp_path):
    config, db, run_id, request_sha = _runtime_with_authorization(tmp_path)
    base = datetime.now(timezone.utc)
    permit = AgentAttemptService(config, db).authorize_next(now=base)
    attempt_id = "attempt_" + "d" * 32
    db.record_agent_worker_attempt_event({
        "schema": "mova-agent-attempt-v2", "attempt_id": attempt_id,
        "authorization_id": permit["authorization_id"], "subject_type": "research",
        "subject_id": run_id, "request_sha256": request_sha,
        "event_type": "started", "status": "running", "model": "fixture",
        "input_tokens": None, "output_tokens": None, "duration_ms": None,
        "error_code": None, "output_present": None, "occurred_at": base.isoformat(),
    }, receipt_path="fixture.started.json", receipt_sha256="e" * 64)

    state = assess_agent_queue(
        config, db, now=base + timedelta(seconds=901), max_started_age_seconds=900
    )

    assert state["healthy"] is False
    assert state["anomalies"][0]["reason"] == "authorization_started_stale"
    assert state["anomalies"][0]["age_seconds"] == 901


def test_watchdog_detects_orphan_permit_file_after_grace(tmp_path):
    config = RuntimeConfig(
        ops_db=tmp_path / "ops.db", research_root=tmp_path / "research",
        sqlite_min_version="0.0.0",
    )
    db = OpsDB(config.ops_db, enforce_version=False)
    db.migrate()
    orphan = config.research_root / "permits" / "orphan.permit.json"
    orphan.parent.mkdir(parents=True)
    orphan.write_text("{}\n", encoding="utf-8")
    old = datetime.now(timezone.utc).timestamp() - 120
    os.utime(orphan, (old, old))

    state = assess_agent_queue(config, db)

    assert state["healthy"] is False
    assert state["permits"] == 1
    assert state["anomalies"][0]["reason"] == "orphan_permit"
