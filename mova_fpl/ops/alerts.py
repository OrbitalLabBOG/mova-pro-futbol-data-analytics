"""Dispatcher local y auditable de alertas del control plane."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

from mova_fpl.ops.db import OpsDB

LOG = logging.getLogger(__name__)


def journal_sink(event: dict) -> None:
    payload = json.loads(event.get("payload_json") or "{}")
    LOG.warning("mova_alert", extra={"event": "mova_alert", "detail": {
        "outbox_id": event["outbox_id"], "event_key": event["event_key"],
        "event_type": event["event_type"], "severity": event["severity"],
        "incident_id": payload.get("incident_id"), "title": payload.get("title"),
        "attempt": event["attempts"],
    }})


def dispatch(db: OpsDB, *, limit: int = 20,
             sink: Callable[[dict], None] = journal_sink) -> dict:
    claimed = db.claim_outbox(limit=limit)
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
