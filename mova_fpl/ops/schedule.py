"""Políticas temporales compartidas por el control plane."""

from __future__ import annotations

from datetime import datetime, timezone


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
