"""Opt-in weekly lineup delivery; never extends the sporting authority of lineup-v1."""
from datetime import datetime

POLICY = 'progressive-lineup-v1'
OPEN_SECONDS = 72 * 3600
FINAL_SECONDS = 3 * 3600
CLOSE_SECONDS = 30 * 60


def enabled(controls):
    return (controls.get('delivery_scope') == 'lineup-v1'
            and controls.get('delivery_policy') == POLICY)


def stage(controls, deadline, now):
    if not enabled(controls):
        return None
    seconds = (datetime.fromisoformat(str(deadline).replace('Z', '+00:00')) - now).total_seconds()
    if not CLOSE_SECONDS < seconds <= OPEN_SECONDS:
        return None
    return 'provisional' if seconds > FINAL_SECONDS else 'final'


def cadence(seconds):
    return 3600 if seconds > 6 * 3600 else 900 if seconds > FINAL_SECONDS else 300
