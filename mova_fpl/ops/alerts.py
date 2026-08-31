"""Dispatcher local y auditable de alertas del control plane."""

from __future__ import annotations

import json
import logging
import hashlib
import http.client
import ipaddress
import socket
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB, new_id, sha256_json

LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WebhookSettings:
    url: str
    owner: str
    channel: str
    timeout_seconds: int = 5


def _load_settings(config: RuntimeConfig) -> WebhookSettings | None:
    """Lee el secreto sin incluir URL, path ni token en respuestas o logs."""
    path = config.alert_webhook_config_file
    if not path.is_file():
        return None
    raw = path.read_bytes()
    if len(raw) > 16_384:
        raise ValueError("alert webhook config exceeds 16 KiB")
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ValueError("alert webhook config version invalid")
    if value.get("enabled") is not True:
        return None
    allowed = {"version", "enabled", "url", "owner", "channel"}
    if set(value) - allowed:
        raise ValueError("alert webhook config has unknown fields")
    owner = str(value.get("owner") or "").strip()
    channel = str(value.get("channel") or "").strip()
    url = str(value.get("url") or "").strip()
    if not owner or len(owner) > 100 or not channel or len(channel) > 100:
        raise ValueError("alert webhook owner/channel invalid")
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.fragment or parsed.port not in (None, 443)):
        raise ValueError("alert webhook URL must be credential-free HTTPS on port 443")
    return WebhookSettings(
        url=url, owner=owner, channel=channel,
        timeout_seconds=config.alert_webhook_timeout_seconds,
    )


def _public_addresses(hostname: str) -> tuple[str, ...]:
    addresses = sorted({row[4][0] for row in socket.getaddrinfo(
        hostname, 443, type=socket.SOCK_STREAM,
    )})
    if not addresses or any(not ipaddress.ip_address(item).is_global for item in addresses):
        raise ValueError("alert webhook destination is not globally routable")
    return tuple(addresses)


def _payload(event: dict, settings: WebhookSettings) -> dict:
    source = json.loads(event.get("payload_json") or "{}")
    return {
        "schema": "mova-alert-webhook-v1",
        "event_key": str(event["event_key"]),
        "event_type": str(event["event_type"]),
        "severity": str(event["severity"]),
        "created_at": str(event["created_at"]),
        "attempt": int(event["attempts"]),
        "incident_id": source.get("incident_id"),
        "probe_id": source.get("probe_id"),
        "destination_fingerprint": source.get("destination_fingerprint"),
        "title": source.get("title"),
        "owner": settings.owner,
        "channel": settings.channel,
    }


def _https_post(settings: WebhookSettings, body: bytes) -> int:
    parsed = urlsplit(settings.url)
    _public_addresses(str(parsed.hostname))
    target = parsed.path or "/"
    if parsed.query:
        target += "?" + parsed.query
    connection = http.client.HTTPSConnection(
        str(parsed.hostname), 443, timeout=settings.timeout_seconds,
        context=ssl.create_default_context(),
    )
    try:
        connection.request(
            "POST", target, body=body,
            headers={"Content-Type": "application/json", "User-Agent": "mova-fpl/1"},
        )
        response = connection.getresponse()
        response.read(4096)
        if not 200 <= response.status < 300:
            raise RuntimeError(f"alert webhook HTTP {response.status}")
        return int(response.status)
    finally:
        connection.close()


def webhook_sink(settings: WebhookSettings, *,
                 transport: Callable[[WebhookSettings, bytes], int] = _https_post
                 ) -> Callable[[dict], None]:
    def sink(event: dict) -> None:
        journal_sink(event)
        body = json.dumps(
            _payload(event, settings), ensure_ascii=False, sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        transport(settings, body)
    return sink


def configured_sink(config: RuntimeConfig) -> Callable[[dict], None]:
    settings = _load_settings(config)
    return journal_sink if settings is None else webhook_sink(settings)


def channel_status(config: RuntimeConfig) -> dict:
    try:
        settings = _load_settings(config)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"schema": "mova-alert-channel-v1", "status": "invalid",
                "configured": False, "external_delivery": False,
                "error_code": type(exc).__name__}
    if settings is None:
        return {"schema": "mova-alert-channel-v1", "status": "local_only",
                "configured": False, "external_delivery": False,
                "owner": None, "channel": "journald"}
    # 128 bits ligan evidencia al destino sin revelar su URL.
    fingerprint = hashlib.sha256(settings.url.encode()).hexdigest()[:32]
    return {"schema": "mova-alert-channel-v1", "status": "configured",
            "configured": True, "external_delivery": True,
            "owner": settings.owner, "channel": settings.channel,
            "destination_fingerprint": fingerprint}


def channel_report(config: RuntimeConfig, db: OpsDB) -> dict:
    report = channel_status(config)
    fingerprint = report.get("destination_fingerprint")
    live = (db.alert_channel_live_status(str(fingerprint)) if fingerprint else
            {"status": "missing", "delivered": False, "external_calls": 0})
    return {**report, "live_test": live}


def channel_prometheus(status: dict) -> str:
    state = str(status.get("status") or "invalid").replace('"', "")
    return "\n".join((
        "# HELP mova_alert_channel_configured External alert channel is configured.",
        "# TYPE mova_alert_channel_configured gauge",
        f"mova_alert_channel_configured {1 if status.get('configured') else 0}",
        "# HELP mova_alert_channel_status Sanitized external alert channel state.",
        "# TYPE mova_alert_channel_status gauge",
        f'mova_alert_channel_status{{status="{state}"}} 1',
        "# HELP mova_alert_channel_live_proven Current destination has a successful live ping.",
        "# TYPE mova_alert_channel_live_proven gauge",
        f"mova_alert_channel_live_proven {1 if (status.get('live_test') or {}).get('delivered') else 0}",
        "",
    ))


def channel_drill() -> dict:
    """Ensaya contrato, redacción y fallos sin DNS ni red externa."""
    captured: list[dict] = []
    settings = WebhookSettings(
        url="https://alerts.example.test/hook/private-token",
        owner="operator", channel="test",
    )
    event = {
        "outbox_id": "outbox_drill", "event_key": "incident:inc_drill",
        "event_type": "incident_opened", "severity": "P0",
        "created_at": "2026-01-01T00:00:00+00:00", "attempts": 1,
        "payload_json": json.dumps({
            "incident_id": "inc_drill", "title": "scheduler down",
            "private_team": "must-not-leak", "token": "must-not-leak",
        }),
    }

    def capture(_settings: WebhookSettings, body: bytes) -> int:
        captured.append(json.loads(body))
        return 204

    webhook_sink(settings, transport=capture)(event)
    failure_propagated = False
    try:
        webhook_sink(settings, transport=lambda _s, _b: (_ for _ in ()).throw(
            RuntimeError("down")
        ))(event)
    except RuntimeError:
        failure_propagated = True
    payload = captured[0]
    checks = {
        "delivery_contract": len(captured) == 1,
        "minimal_allowlist": set(payload) == {
            "schema", "event_key", "event_type", "severity", "created_at", "attempt",
            "incident_id", "probe_id", "destination_fingerprint", "title", "owner", "channel",
        },
        "private_fields_redacted": "private_team" not in payload and "token" not in payload,
        "destination_secret_redacted": "url" not in payload,
        "failure_propagates_to_outbox": failure_propagated,
        "runtime_not_mutated": True,
    }
    return {"schema": "mova-alert-channel-drill-v1",
            "status": "pass" if all(checks.values()) else "fail",
            "checks": checks, "external_calls": 0, "runtime_mutated": False}


def journal_sink(event: dict) -> None:
    payload = json.loads(event.get("payload_json") or "{}")
    LOG.warning("mova_alert", extra={"event": "mova_alert", "detail": {
        "outbox_id": event["outbox_id"], "event_key": event["event_key"],
        "event_type": event["event_type"], "severity": event["severity"],
        "incident_id": payload.get("incident_id"), "title": payload.get("title"),
        "attempt": event["attempts"],
    }})


def dispatch(db: OpsDB, *, limit: int = 20, outbox_id: str | None = None,
             sink: Callable[[dict], None] = journal_sink) -> dict:
    claimed = ([event] if (outbox_id and (event := db.claim_outbox_by_id(outbox_id)))
               else [] if outbox_id else db.claim_outbox(limit=limit))
    delivered = failed = dead = 0
    for event in claimed:
        try:
            sink(event)
        except Exception as exc:  # noqa: BLE001 - el outbox debe sobrevivir al sink
            status = db.finish_outbox(
                event["outbox_id"], delivered=False, error=type(exc).__name__,
            )
            failed += 1
            dead += int(status == "dead")
        else:
            db.finish_outbox(event["outbox_id"], delivered=True)
            delivered += 1
    return {"schema": "mova-alert-dispatch-v1", "claimed": len(claimed),
            "delivered": delivered, "failed": failed, "dead": dead}


def live_ping(config: RuntimeConfig, db: OpsDB, *, actor: str, reason: str,
              idempotency_key: str,
              sink: Callable[[dict], None] | None = None) -> dict:
    """Prueba el destino configurado una vez, con ledger y outbox aislado."""
    try:
        settings = _load_settings(config)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"schema": "mova-alert-live-ping-v1", "status": "not_configured",
                "channel_status": "invalid", "error_code": type(exc).__name__,
                "runtime_mutated": False, "external_calls": 0}
    if settings is None:
        return {"schema": "mova-alert-live-ping-v1", "status": "not_configured",
                "channel_status": "local_only", "runtime_mutated": False,
                "external_calls": 0}
    fingerprint = hashlib.sha256(settings.url.encode()).hexdigest()[:32]
    identity = sha256_json({
        "actor": actor, "reason": reason, "idempotency_key": idempotency_key,
        "destination_fingerprint": fingerprint,
    })
    job_key = f"alert_channel_live_ping:{idempotency_key}"
    job_id, reused = db.start_job(
        "alert_channel_live_ping", job_key, new_id("corr"), input_sha256=identity,
    )
    if reused:
        prior = db.get_job_by_key(job_key) or {}
        if prior.get("input_sha256") not in (None, identity):
            return {"schema": "mova-alert-live-ping-v1", "status": "conflict",
                    "error_code": "idempotency_identity_mismatch",
                    "runtime_mutated": False, "external_calls": 0}
        prior_metrics = json.loads(prior.get("metrics_json") or "{}")
        return {"schema": "mova-alert-live-ping-v1",
                "status": "reused" if prior.get("status") == "completed" else prior.get("status"),
                "job_id": job_id, "destination_fingerprint": fingerprint,
                "delivered": prior_metrics.get("delivered") is True,
                "external_calls": 0, "runtime_mutated": False}
    db.append_audit(
        "alert_channel_live_ping_requested", actor=actor, job_id=job_id,
        subject_type="alert_channel", subject_id=fingerprint,
        payload={"reason": reason, "destination_fingerprint": fingerprint},
    )
    try:
        outbox_id = db.enqueue_alert_probe(
            job_id=job_id, correlation_id=str(
                (db.get_job_by_key(job_key) or {}).get("correlation_id") or ""
            ), destination_fingerprint=fingerprint,
        )
        result = dispatch(
            db, outbox_id=outbox_id, sink=sink or webhook_sink(settings),
        )
    except Exception as exc:  # ledger terminal incluso ante una falla interna
        db.finish_job(job_id, "failed", error_code=type(exc).__name__)
        return {"schema": "mova-alert-live-ping-v1", "status": "failed",
                "job_id": job_id, "destination_fingerprint": fingerprint,
                "delivered": False, "external_calls": 0,
                "runtime_mutated": True, "error_code": type(exc).__name__}
    delivered = result["delivered"] == 1 and result["failed"] == 0
    metrics = {"destination_fingerprint": fingerprint, "delivered": delivered,
               "external_calls": result["claimed"], "outbox_id": outbox_id}
    payload = {"schema": "mova-alert-live-ping-v1",
               "status": "pass" if delivered else "failed", "job_id": job_id,
               "destination_fingerprint": fingerprint, "delivered": delivered,
               "external_calls": result["claimed"], "runtime_mutated": True,
               "outbox": db.outbox_event_status(outbox_id)}
    db.finish_job(
        job_id, "completed" if delivered else "failed",
        output_sha256=sha256_json(payload), metrics=metrics,
        error_code=None if delivered else "AlertDeliveryFailed",
    )
    return payload
