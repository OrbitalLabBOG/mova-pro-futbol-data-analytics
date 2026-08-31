"""Entrega at-least-once, retry y ack del outbox operativo."""

from __future__ import annotations

from pathlib import Path

from mova_fpl.ops.alerts import dispatch
from mova_fpl.ops.db import OpsDB


def _db(tmp_path: Path) -> OpsDB:
    db = OpsDB(tmp_path / "ops.db", enforce_version=False)
    db.migrate()
    return db


def test_dispatch_delivers_once_and_keeps_payload_sanitized_in_status(tmp_path):
    db = _db(tmp_path)
    incident = db.open_incident(
        "P1", "collector stale", detail={"error_code": "StaleSource"},
    )
    delivered = []

    first = dispatch(db, sink=lambda event: delivered.append(event["event_key"]))
    second = dispatch(db, sink=lambda event: delivered.append(event["event_key"]))

    assert first == {"schema": "mova-alert-dispatch-v1", "claimed": 1,
                     "delivered": 1, "failed": 0, "dead": 0}
    assert second["claimed"] == 0
    assert delivered == [f"incident:{incident}"]
    status = db.outbox_status()
    assert status["counts"]["sent"]["P1"] == 1
    assert "payload_json" not in status["latest"][0]


def test_dispatch_failure_is_retriable_and_ack_is_audited(tmp_path):
    db = _db(tmp_path)
    incident = db.open_incident("P0", "runtime down")

    failed = dispatch(db, sink=lambda _event: (_ for _ in ()).throw(RuntimeError("secret")))
    assert failed["failed"] == 1
    row = db.outbox_status()["latest"][0]
    assert row["status"] == "pending"
    assert row["last_error"] == "RuntimeError"

    ack = db.acknowledge_incident(incident, actor="operator", reason="triaged")
    reused = db.acknowledge_incident(incident, actor="operator", reason="triaged")
    assert ack["status"] == "acknowledged" and not ack["reused"]
    assert reused["reused"]
    assert db.outbox_status()["latest"][0]["status"] == "acknowledged"
    with db.connect(readonly=True) as con:
        events = {row[0] for row in con.execute("SELECT event_type FROM audit_events")}
    assert {"alert_delivery_failed", "incident_acknowledged"} <= events


def test_expired_sending_lease_is_reclaimed(tmp_path):
    db = _db(tmp_path)
    db.open_incident("P2", "lease recovery")
    claimed = db.claim_outbox(lease_seconds=0)
    assert len(claimed) == 1
    reclaimed = db.claim_outbox()
    assert len(reclaimed) == 1
    assert reclaimed[0]["attempts"] == 2
