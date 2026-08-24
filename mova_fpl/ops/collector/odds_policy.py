"""Política pura de muestreo de odds guiada por deadline y cuota mensual."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone


def _aware(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    parsed = (datetime.fromisoformat(value.replace("Z", "+00:00"))
              if isinstance(value, str) else value)
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


@dataclass(frozen=True, slots=True)
class OddsPlan:
    due: bool
    reason: str
    tier: str
    cadence_seconds: int
    regions: str
    markets: str
    planned_cost: int
    deadline_event: int | None
    deadline_time: str | None
    hours_to_deadline: float | None
    quota_remaining: int | None

    def as_dict(self) -> dict:
        return asdict(self)


def _cursor_quality(cursor: dict | None) -> dict:
    return ((cursor or {}).get("detail") or {}).get("quality") or {}


def plan_collection(config, *, now: datetime, deadline: dict | None,
                    cursor: dict | None, force: bool = False) -> OddsPlan:
    """Decide sin red. ``force`` omite cadencia, nunca las reservas de cuota."""
    markets = ",".join(dict.fromkeys(filter(None, (
        item.strip() for item in config.odds_api_markets.split(",")
    ))))
    event = int(deadline["event_id"]) if deadline else None
    deadline_at = _aware(deadline.get("deadline_time") if deadline else None)
    hours = ((deadline_at - now).total_seconds() / 3600 if deadline_at else None)
    quality = _cursor_quality(cursor)
    quota = quality.get("quota") or {}
    remaining = quota.get("remaining")
    remaining = int(remaining) if remaining is not None else None

    if hours is None or hours <= 0:
        tier, cadence, reason = "paused", 24 * 3600, "no_future_fpl_deadline"
        regions = config.odds_api_regular_regions
    elif hours > 72:
        tier, cadence, reason = "baseline", 24 * 3600, "adaptive_cadence"
        regions = config.odds_api_regular_regions
    elif hours > 24:
        tier, cadence, reason = "approach", 12 * 3600, "adaptive_cadence"
        regions = config.odds_api_regular_regions
    elif hours > 6:
        tier, cadence, reason = "decision", 6 * 3600, "adaptive_cadence"
        regions = config.odds_api_regular_regions
    else:
        tier, cadence, reason = "deadline", 6 * 3600, "adaptive_cadence"
        regions = config.odds_api_regions

    cost = len(set(filter(None, regions.split(",")))) * len(set(filter(None, markets.split(","))))
    base = dict(tier=tier, cadence_seconds=cadence, regions=regions, markets=markets,
                planned_cost=cost, deadline_event=event,
                deadline_time=deadline_at.isoformat() if deadline_at else None,
                hours_to_deadline=round(hours, 3) if hours is not None else None,
                quota_remaining=remaining)
    if hours is None or hours <= 0:
        return OddsPlan(False, reason, **base)

    previous_policy = quality.get("policy") or {}
    if (tier == "deadline" and previous_policy.get("tier") == "deadline"
            and previous_policy.get("deadline_event") == event):
        return OddsPlan(False, "deadline_checkpoint_already_collected", **base)

    # La reserva media restringe snapshots de baja urgencia; la reserva dura
    # conserva únicamente el último checkpoint. El proveedor reinicia el
    # contador y el header creciente libera el gate sin intervención.
    if remaining is not None:
        if remaining < cost:
            return OddsPlan(False, "insufficient_provider_quota", **base)
        if remaining < config.odds_api_hard_reserve_credits and hours > 1:
            return OddsPlan(False, "hard_reserve_final_hour_only", **base)
        if remaining < config.odds_api_reserve_credits and hours > 24:
            return OddsPlan(False, "reserve_decision_window_only", **base)

    observed = None
    if cursor:
        observed = (cursor.get("last_attempt_at") if cursor.get("last_status") == "failed"
                    else cursor.get("last_success_at"))
    observed = _aware(observed)
    due = force or observed is None or (now - observed).total_seconds() >= cadence
    return OddsPlan(due, "forced" if force else reason, **base)
