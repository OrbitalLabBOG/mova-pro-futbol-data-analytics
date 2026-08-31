"""Entrega at-least-once, retry y ack del outbox operativo."""

from __future__ import annotations

from pathlib import Path

import json

from mova_fpl.ops.alerts import (
    WebhookSettings, channel_drill, channel_prometheus, channel_status, dispatch,
    webhook_sink,
)
from mova_fpl.ops.config import RuntimeConfig
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


def test_dead_event_requires_audited_retry_or_ack(tmp_path):
    db = _db(tmp_path)
    incident = db.open_incident("P0", "delivery unavailable")
    event = db.claim_outbox()[0]
    assert db.finish_outbox(
        event["outbox_id"], delivered=False, error="SinkDown", max_attempts=1,
    ) == "dead"

    retried = db.retry_outbox(
        event["outbox_id"], actor="operator", reason="sink restored",
    )
    assert retried["status"] == "pending" and not retried["reused"]
    assert db.retry_outbox(
        event["outbox_id"], actor="operator", reason="same request",
    )["reused"]

    event = db.claim_outbox()[0]
    db.finish_outbox(event["outbox_id"], delivered=False, max_attempts=1)
    db.acknowledge_incident(incident, actor="operator", reason="triaged elsewhere")
    assert db.outbox_status()["latest"][0]["status"] == "acknowledged"


def test_alert_channel_is_local_only_without_secret(tmp_path):
    status = channel_status(RuntimeConfig(alert_webhook_config_file=tmp_path / "missing"))
    assert status == {"schema": "mova-alert-channel-v1", "status": "local_only",
                      "configured": False, "external_delivery": False,
                      "owner": None, "channel": "journald"}
    assert "mova_alert_channel_configured 0" in channel_prometheus(status)


def test_alert_channel_status_never_exposes_webhook_url(tmp_path):
    secret = tmp_path / "webhook.json"
    secret.write_text(json.dumps({
        "version": 1, "enabled": True,
        "url": "https://alerts.example.test/private/token",
        "owner": "operator", "channel": "personal",
    }))
    status = channel_status(RuntimeConfig(alert_webhook_config_file=secret))
    assert status["status"] == "configured"
    assert status["owner"] == "operator"
    assert "url" not in status and "token" not in json.dumps(status)


def test_webhook_sink_uses_minimal_payload():
    bodies = []
    sink = webhook_sink(
        WebhookSettings("https://alerts.example.test/private", "owner", "channel"),
        transport=lambda _settings, body: bodies.append(json.loads(body)) or 204,
    )
    sink({"outbox_id": "o", "event_key": "incident:i", "event_type": "opened",
          "severity": "P0", "created_at": "now", "attempts": 1,
          "payload_json": json.dumps({"incident_id": "i", "title": "down",
                                      "secret": "never"})})
    assert bodies[0]["incident_id"] == "i"
    assert "secret" not in bodies[0]


def test_alert_channel_drill_is_hermetic_and_complete():
    result = channel_drill()
    assert result["status"] == "pass"
    assert result["external_calls"] == 0
    assert result["runtime_mutated"] is False
    assert all(result["checks"].values())
