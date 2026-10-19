"""Entrega at-least-once, retry y ack del outbox operativo."""

from __future__ import annotations

from pathlib import Path

import json

from mova_fpl.ops.alerts import (
    SlackSettings, WebhookSettings, channel_drill, channel_prometheus,
    channel_report, channel_status, dispatch, live_ping, slack_sink, webhook_sink,
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
    config = RuntimeConfig(alert_webhook_config_file=tmp_path / "missing")
    status = channel_status(config)
    assert status == {"schema": "mova-alert-channel-v1", "status": "local_only",
                      "configured": False, "external_delivery": False,
                      "owner": None, "channel": "journald"}
    report = channel_report(config, _db(tmp_path))
    assert report["live_test"]["status"] == "missing"
    assert "mova_alert_channel_configured 0" in channel_prometheus(report)
    assert "mova_alert_channel_live_proven 0" in channel_prometheus(report)


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


def test_slack_sink_uses_fixed_user_and_redacted_message(tmp_path):
    config_file = tmp_path / "alert.json"
    config_file.write_text(json.dumps({
        "version": 2, "enabled": True, "provider": "slack",
        "token": "xoxb-123456789012345", "recipient_user_id": "U08GJTQDZ2T",
        "owner": "julian",
    }))
    status = channel_status(RuntimeConfig(alert_webhook_config_file=config_file))
    assert status["status"] == "configured"
    assert status["owner"] == "julian" and status["channel"] == "slack_dm"
    assert "xoxb" not in json.dumps(status) and "U08GJTQDZ2T" not in json.dumps(status)
    bodies = []
    sink = slack_sink(SlackSettings("xoxb-123456789012345", "U08GJTQDZ2T", "julian"),
                      transport=lambda _settings, body: bodies.append(json.loads(body)) or 200)
    sink({"outbox_id": "o", "event_key": "incident:i", "event_type": "opened",
          "severity": "P0", "created_at": "now", "attempts": 1,
          "payload_json": json.dumps({"incident_id": "i", "title": "runtime down",
                                      "secret": "never"})})
    assert bodies == [{"channel": "U08GJTQDZ2T",
                       "text": "MOVA FPL P0: runtime down\nEvento: incident:i",
                       "unfurl_links": False, "unfurl_media": False}]


def test_alert_channel_drill_is_hermetic_and_complete():
    result = channel_drill()
    assert result["status"] == "pass"
    assert result["external_calls"] == 0
    assert result["runtime_mutated"] is False
    assert all(result["checks"].values())


def _configured(tmp_path) -> RuntimeConfig:
    secret = tmp_path / "webhook.json"
    secret.write_text(json.dumps({
        "version": 1, "enabled": True,
        "url": "https://alerts.example.test/private/token",
        "owner": "operator", "channel": "test",
    }))
    return RuntimeConfig(alert_webhook_config_file=secret)


def test_live_ping_is_fail_closed_without_config_and_does_not_create_job(tmp_path):
    db = _db(tmp_path)
    result = live_ping(
        RuntimeConfig(alert_webhook_config_file=tmp_path / "missing"), db,
        actor="operator", reason="prove", idempotency_key="ping-v1",
    )
    assert result["status"] == "not_configured"
    assert result["runtime_mutated"] is False
    assert db.alert_channel_live_status()["status"] == "missing"


def test_live_ping_isolated_delivery_replay_and_identity_conflict(tmp_path):
    db = _db(tmp_path)
    config = _configured(tmp_path)
    incident_id = db.open_incident("P0", "neighbor must remain pending")
    delivered = []
    sink = lambda event: delivered.append(event["event_key"])
    first = live_ping(
        config, db, actor="operator", reason="prove", idempotency_key="ping-v1",
        sink=sink,
    )
    replay = live_ping(
        config, db, actor="operator", reason="prove", idempotency_key="ping-v1",
        sink=sink,
    )
    conflict = live_ping(
        config, db, actor="operator", reason="different", idempotency_key="ping-v1",
        sink=sink,
    )
    assert first["status"] == "pass" and first["delivered"] is True
    assert replay["status"] == "reused" and replay["external_calls"] == 0
    assert conflict["status"] == "conflict" and conflict["external_calls"] == 0
    assert delivered == [f"alert_probe:{first['job_id']}"]
    with db.connect(readonly=True) as con:
        neighbor = con.execute(
            "SELECT status,attempts FROM outbox_events WHERE event_key=?",
            (f"incident:{incident_id}",),
        ).fetchone()
    assert (neighbor["status"], neighbor["attempts"]) == ("pending", 0)
    status = db.alert_channel_live_status(first["destination_fingerprint"])
    assert status["status"] == "completed" and status["delivered"] is True
    assert channel_report(config, db)["live_test"]["job_id"] == first["job_id"]


def test_live_ping_failure_stays_auditable_and_retriable(tmp_path):
    db = _db(tmp_path)
    result = live_ping(
        _configured(tmp_path), db, actor="operator", reason="prove failure",
        idempotency_key="ping-fail",
        sink=lambda _event: (_ for _ in ()).throw(RuntimeError("secret detail")),
    )
    assert result["status"] == "failed" and result["delivered"] is False
    assert result["outbox"]["status"] == "pending"
    assert result["outbox"]["last_error"] == "RuntimeError"
    assert "secret detail" not in json.dumps(result)
    assert db.alert_channel_live_status()["status"] == "failed"


def test_api_observes_worker_channel_without_delivery_secret(tmp_path):
    from dataclasses import replace
    from mova_fpl.ops.alerts import configured_sink, journal_sink, publish_channel_status
    secret = tmp_path / 'webhook.json'
    secret.write_text(json.dumps({'version': 1, 'enabled': True,
                                 'url': 'https://alerts.example.test/private-token',
                                 'owner': 'julian', 'channel': 'test'}))
    worker = RuntimeConfig(alert_webhook_config_file=secret,
                           host_probe_path=tmp_path / 'runtime' / 'host-probe.json')
    path = publish_channel_status(worker)
    api = replace(worker, alert_webhook_config_file=tmp_path / 'absent-secret',
                  alert_channel_status_file=path)
    assert channel_status(api) == channel_status(worker)
    assert channel_status(api)['configured'] is True
    assert configured_sink(api) is journal_sink  # status is never delivery authority
    assert 'private-token' not in path.read_text()
    assert 'https://' not in path.read_text()
    secret.unlink()
    assert channel_status(worker)['status'] == 'local_only'  # never falls back to cache
    publish_channel_status(worker)
    assert channel_status(api)['status'] == 'local_only'


def test_api_channel_projection_rejects_stale_future_corrupt_or_secret_data(tmp_path):
    from datetime import datetime, timedelta, timezone
    path = tmp_path / 'alert-channel.json'
    api = RuntimeConfig(alert_channel_status_file=path)
    assert channel_status(api)['status'] == 'invalid'
    for delta in (-1801, 60):
        path.write_text(json.dumps({
            'schema': 'mova-alert-channel-observation-v1',
            'generated_at': (datetime.now(timezone.utc) + timedelta(seconds=delta)).isoformat(),
            'channel': {'schema': 'mova-alert-channel-v1', 'status': 'local_only',
                        'configured': False, 'external_delivery': False},
        }))
        assert channel_status(api)['status'] == 'invalid'
    for content in ('{', '[]', 'x' * 4097):
        path.write_text(content)
        assert channel_status(api)['configured'] is False
    path.write_text(json.dumps({
        'schema': 'mova-alert-channel-observation-v1',
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'channel': {'schema': 'mova-alert-channel-v1', 'status': 'configured',
                    'configured': True, 'external_delivery': True, 'token': 'do-not-expose'},
    }))
    assert 'do-not-expose' not in json.dumps(channel_status(api))
    assert channel_status(api)['configured'] is False


def test_compose_api_uses_observation_and_worker_retains_delivery_config():
    compose = Path('compose.yaml').read_text()
    api = compose.split('  api:\n', 1)[1].split('  worker:\n', 1)[0]
    worker = compose.split('  worker:\n', 1)[1].split('  browser:\n', 1)[0]
    assert 'MOVA_ALERT_CHANNEL_STATUS_FILE: /var/lib/mova-fpl/runtime/alert-channel.json' in api
    assert 'environment: &engine_environment' in compose
    assert '<<: *engine_environment' in api
    assert 'secrets:' not in api
    assert '- alert_webhook_config' in worker
    assert 'MOVA_ALERT_CHANNEL_STATUS_FILE' not in worker


def test_resolved_unsent_alert_is_superseded_without_a_recovery_spam(tmp_path):
    import pytest
    db = _db(tmp_path)
    db.open_incident('P1', 'disk full')
    opening = db.outbox_status()['latest'][0]['outbox_id']
    assert db.resolve_incidents('disk full', resolution='disk recovered') == 1
    assert db.resolve_incidents('disk full', resolution='repeat') == 0
    assert db.outbox_event_status(opening)['status'] == 'superseded'
    assert db.outbox_event_status(opening)['sent_at'] is None
    assert dispatch(db, sink=lambda _: pytest.fail('obsolete message sent'))['claimed'] == 0
    with pytest.raises(ValueError):
        db.retry_outbox(opening, actor='test', reason='must not resurrect')


def test_many_notified_incidents_close_with_one_recovery_and_no_raw_detail(tmp_path):
    db = _db(tmp_path)
    for _ in range(3):
        db.open_incident('P1', 'disk full', detail={'error': 'secret'})
    dispatch(db, sink=lambda _: None)
    assert db.resolve_incidents('disk full', resolution='secret resolution') == 3
    delivered = []
    assert dispatch(db, sink=delivered.append)['delivered'] == 1
    event = delivered[0]
    assert event['event_type'] == 'incident_recovered'
    assert json.loads(event['payload_json'])['resolved_count'] == 3
    assert 'secret' not in event['payload_json']
    assert dispatch(db, sink=delivered.append)['claimed'] == 0


def test_resolution_between_batch_claim_and_send_suppresses_obsolete_opening(tmp_path):
    db = _db(tmp_path)
    db.open_incident('P1', 'first')
    db.open_incident('P1', 'second')
    delivered = []
    def sink(event):
        delivered.append(event)
        if len(delivered) == 1:
            db.resolve_incidents('second', resolution='recovered during batch')
    result = dispatch(db, sink=sink)
    assert result['delivered'] == 1 and result['suppressed'] == 1
    assert all(json.loads(e['payload_json'])['title'] != 'second' for e in delivered)


def test_slack_opening_contains_safe_cause_and_recovery_has_duration(tmp_path):
    db = _db(tmp_path)
    db.open_incident('P1', 'Tick MOVA falló', detail={
        'error': 'disk gate: 18413924352 < 21474836480', 'secret': 'do-not-print'})
    bodies = []
    sink = slack_sink(SlackSettings('xoxb-unused', 'U08GJTQDZ2T', 'julian'),
                      transport=lambda _, body: bodies.append(json.loads(body)) or 200)
    dispatch(db, sink=sink)
    assert '17.1 GiB; mínimo 20.0 GiB' in bodies[0]['text']
    assert 'Inicio:' in bodies[0]['text'] and 'do-not-print' not in str(bodies)
    db.resolve_incidents('Tick MOVA falló', resolution='recovered')
    dispatch(db, sink=sink)
    assert 'RECUPERADO' in bodies[1]['text'] and 'Duración:' in bodies[1]['text']


def test_slack_failure_code_is_sanitized_and_rate_limit_defers_retry(tmp_path):
    from mova_fpl.ops.alerts import SlackDeliveryError
    db = _db(tmp_path)
    db.open_incident('P1', 'down')
    result = dispatch(db, sink=lambda _: (_ for _ in ()).throw(
        SlackDeliveryError('slack_rate_limited', 900)))
    assert result['failed'] == 1
    row = db.outbox_status()['latest'][0]
    assert row['last_error'] == 'slack_rate_limited'
    from datetime import datetime
    assert (datetime.fromisoformat(row['available_at']) - datetime.fromisoformat(row['created_at'])).total_seconds() >= 900
    assert dispatch(db, sink=lambda _: None)['claimed'] == 0


def test_alert_schema_upgrade_preserves_history_and_admits_supersession(tmp_path):
    from mova_fpl.ops.schema import MIGRATIONS
    import sqlite3
    db = OpsDB(tmp_path / 'old.db', enforce_version=False)
    # Build the previous schema through the same migration contract.
    import mova_fpl.ops.db as db_module
    from unittest.mock import patch
    with patch.object(db_module, 'MIGRATIONS', MIGRATIONS[:-1]):
        db.migrate()
    incident = db.open_incident('P1', 'preserved')
    dispatch(db, sink=lambda _: None)
    db.migrate()
    assert db.incident(incident)['title'] == 'preserved'
    assert db.outbox_status()['counts']['sent']['P1'] == 1
    assert db.quick_check() == 'ok'


def test_slack_transport_records_only_allowlisted_errors(monkeypatch):
    import mova_fpl.ops.alerts as alerts
    import pytest
    monkeypatch.setattr(alerts, '_public_addresses', lambda _: ('8.8.8.8',))
    class Response:
        status = 200
        body = b'{"ok":false,"error":"missing_scope","needed":"secret"}'
        def read(self, _): return self.body
        def getheader(self, _): return '900'
    response = Response()
    class Connection:
        def __init__(self, *a, **kw): pass
        def request(self, *a, **kw): pass
        def getresponse(self): return response
        def close(self): pass
    monkeypatch.setattr(alerts.http.client, 'HTTPSConnection', Connection)
    settings = SlackSettings('xoxb-unused', 'U08GJTQDZ2T', 'test')
    for status, body, expected in [
        (200, b'{"ok":false,"error":"missing_scope","private":"secret"}', 'slack_missing_scope'),
        (200, b'{"ok":false,"error":"invalid_auth"}', 'slack_authentication_failed'),
        (200, b'{"ok":false,"error":"unexpected-secret"}', 'slack_delivery_rejected'),
        (200, b'[]', 'slack_invalid_response'),
        (503, b'secret', 'slack_unavailable'),
        (429, b'secret', 'slack_rate_limited'),
    ]:
        response.status, response.body = status, body
        with pytest.raises(alerts.SlackDeliveryError) as caught:
            alerts._slack_post(settings, b'{}')
        assert str(caught.value) == expected
        assert 'secret' not in str(caught.value)
        if status == 429: assert caught.value.retry_seconds == 900


def test_superseded_retry_failure_never_resurrects_a_resolved_incident(tmp_path):
    db = _db(tmp_path)
    db.open_incident('P1', 'recovery during network failure')
    event = db.claim_outbox()[0]
    db.resolve_incidents('recovery during network failure', resolution='restored')
    # The sending event is suppressed at the last state check.
    assert db.alert_delivery_context(event) is None
    assert db.finish_outbox(event['outbox_id'], delivered=False) == 'superseded'
    assert db.outbox_event_status(event['outbox_id'])['status'] == 'superseded'
