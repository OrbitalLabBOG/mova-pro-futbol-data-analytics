"""Políticas temporales compartidas por el control plane."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


PUBLIC_CADENCE_SECONDS = {
    "baseline": 6 * 3600,
    "research": 3 * 3600,
    "refresh": 3600,
    "preflight": 15 * 60,
    "freeze": 5 * 60,
    "execution_window": 5 * 60,
    "verification_window": 5 * 60,
    "hard_stop": 5 * 60,
    "settlement": 6 * 3600,
}

WORKFLOW_TIMING_POLICY_VERSION = "workflow-timing-1.0.0"
# Seconds before the official deadline. These boundaries match phase_for:
# preflight begins at T-6h, freeze at T-90m, execution at T-60m,
# verification at T-30m and hard_stop at T-15m.
WORKFLOW_MILESTONES = {
    "observe": (6 * 3600, 3 * 3600, 30 * 60),
    "contextualize": (3 * 3600, 3600, 30 * 60),
    "research": (6 * 3600, 3 * 3600, 30 * 60),
    "propose_validate": (3 * 3600, 3600, 30 * 60),
    "deliberate": (6 * 3600, 3 * 3600, 30 * 60),
    "preflight": (3 * 3600, 3600, 30 * 60),
    "execute_verify": (3600, 30 * 60, 15 * 60),
}


def workflow_stage_timing(name: str, deadline: datetime | None) -> dict:
    """Expose bounded milestones without treating official settlement as a clock."""
    if name in {"settle", "review_learn"}:
        return {"policy_version": WORKFLOW_TIMING_POLICY_VERSION,
                "basis": "official_finished_data_checked", "target_at": None,
                "recovery_until": None, "hard_stop_at": None}
    offsets = WORKFLOW_MILESTONES.get(name)
    if not offsets or deadline is None:
        return {"policy_version": WORKFLOW_TIMING_POLICY_VERSION,
                "basis": "official_deadline", "target_at": None,
                "recovery_until": None, "hard_stop_at": None}
    target, recovery, hard_stop = offsets
    return {
        "policy_version": WORKFLOW_TIMING_POLICY_VERSION,
        "basis": "official_deadline",
        "target_at": (deadline - timedelta(seconds=target)).isoformat(),
        "recovery_until": (deadline - timedelta(seconds=recovery)).isoformat(),
        "hard_stop_at": (deadline - timedelta(seconds=hard_stop)).isoformat(),
    }


def select_event(boot: dict, now: datetime | None = None) -> dict:
    """Selecciona el próximo ciclo operable desde el bootstrap oficial."""
    now = now or datetime.now(timezone.utc)
    events = list(boot.get("events") or ())
    explicit = next((event for event in events if event.get("is_next")), None)
    if explicit:
        return explicit
    future = []
    for event in events:
        deadline = event.get("deadline_time")
        if not deadline:
            continue
        parsed = datetime.fromisoformat(str(deadline).replace("Z", "+00:00"))
        if parsed > now:
            future.append((parsed, event))
    if future:
        return min(future, key=lambda item: item[0])[1]
    current = next((event for event in events if event.get("is_current")), None)
    if current:
        return current
    raise ValueError("bootstrap sin jornada current/next ni deadline futuro")


def phase_for(deadline: str, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    target = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
    hours = (target - now).total_seconds() / 3600
    if hours > 48:
        return "baseline"
    if hours > 24:
        return "research"
    if hours > 6:
        return "refresh"
    if hours > 1.5:
        return "preflight"
    if hours > 1:
        return "freeze"
    if hours > 0.5:
        return "execution_window"
    if hours > 0.25:
        return "verification_window"
    if hours > 0:
        return "hard_stop"
    return "settlement"


def private_state_cadence_seconds(deadline: str, now: datetime | None = None) -> int:
    """Cadencia del estado privado: 6 h → 1 h → 15 min → 5 min."""
    now = now or datetime.now(timezone.utc)
    target = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
    seconds = (target - now).total_seconds()
    if 0 < seconds <= 30 * 60:
        return 5 * 60
    if 0 < seconds <= 3 * 3600:
        return 15 * 60
    if 0 < seconds <= 24 * 3600:
        return 3600
    return 6 * 3600


def public_state_cadence_seconds(deadline: str, now: datetime | None = None) -> int:
    """Cadencia del snapshot público para la fase efectiva de la jornada."""
    return PUBLIC_CADENCE_SECONDS[phase_for(deadline, now)]
