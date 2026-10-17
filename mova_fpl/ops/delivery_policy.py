"""Explicit, expiring owner approval for a reversible live save proof."""
from datetime import datetime


def lineup_proof(controls: dict, cycle_id: str, now: datetime) -> bool:
    if controls.get('delivery_scope') != 'lineup-v1':
        return False
    approval = controls.get('delivery_proof')
    if not isinstance(approval, dict) or set(approval) != {'cycle_id', 'approved_at', 'expires_at'}:
        return False
    try:
        start = datetime.fromisoformat(approval['approved_at'].replace('Z', '+00:00'))
        end = datetime.fromisoformat(approval['expires_at'].replace('Z', '+00:00'))
        return (approval['cycle_id'] == cycle_id and start.tzinfo is not None and end.tzinfo is not None
                and 0 < (end-start).total_seconds() <= 3600 and start <= now < end)
    except (ValueError, TypeError, AttributeError):
        return False
