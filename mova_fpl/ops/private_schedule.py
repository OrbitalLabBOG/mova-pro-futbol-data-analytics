"""Gate liviano para no abrir el browser si el estado privado sigue fresco."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from mova_fpl.data.sources import fetch_bootstrap
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB
from mova_fpl.ops.schedule import phase_for, private_state_cadence_seconds, select_event


def assess(config: RuntimeConfig, db: OpsDB, *, now: datetime | None = None,
           bootstrap: bytes | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    boot = json.loads(bootstrap if bootstrap is not None else fetch_bootstrap())
    event = select_event(boot, now)
    gw = int(event["id"])
    deadline = str(event["deadline_time"])
    cadence = private_state_cadence_seconds(deadline, now)
    latest = db.latest_team_state_for_event(config.season, gw)
    if latest is None:
        return {
            "due": True, "reason": "no_current_event_snapshot", "season": config.season,
            "gw": gw, "deadline_at": deadline, "phase": phase_for(deadline, now),
            "cadence_seconds": cadence, "age_seconds": None,
        }
    observed = datetime.fromisoformat(str(latest["observed_at"]).replace("Z", "+00:00"))
    age = max(0, int((now - observed).total_seconds()))
    due = age >= cadence or latest.get("quality_status") != "valid"
    return {
        "due": due,
        "reason": "capture_due" if due else "snapshot_fresh",
        "season": config.season,
        "gw": gw,
        "deadline_at": deadline,
        "phase": phase_for(deadline, now),
        "cadence_seconds": cadence,
        "age_seconds": age,
        "last_observed_at": latest["observed_at"],
        "quality_status": latest.get("quality_status"),
    }
