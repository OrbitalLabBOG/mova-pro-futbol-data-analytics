"""Explicit clocks for deadline-dependent operational tests."""
from datetime import datetime, timezone
import pytest


@pytest.fixture
def predeadline_clock(monkeypatch, request):
    from mova_fpl.ops import agent_attempts, db, watchdog

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = cls(2026, 8, 30, 12, tzinfo=timezone.utc)
            return value.astimezone(tz) if tz is not None else value.replace(tzinfo=None)

    for module in (request.module, agent_attempts, db, watchdog):
        monkeypatch.setattr(module, 'datetime', FrozenDateTime)
    return FrozenDateTime.now(timezone.utc)
