from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mova_fpl.ops.cli import parser
from mova_fpl.ops.collector.fpl import validate_bundle
from mova_fpl.ops.collector.odds import parse_csv
from mova_fpl.ops.collector.whoscored import (
    calendar_months,
    normalize_schedule_rows,
    validate_match,
    validate_schedule,
)
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.collector.store import cursor_is_due
from mova_fpl.postgres.store import MIGRATIONS, latest_version


def _fpl_bundle():
    boot = {
        "teams": [{"id": value} for value in range(1, 21)],
        "events": [{"id": value} for value in range(1, 39)],
        "elements": [{"id": value} for value in range(1, 601)],
    }
    fixtures = [{"id": value} for value in range(1, 381)]
    return boot, fixtures, {"id": 99}, {"current": [{"event": 1}]}


def test_fpl_bundle_contract_covers_whole_public_surface():
    quality, checks = validate_bundle(*_fpl_bundle(), 99)
    assert quality == {
        "teams": 20, "events": 38, "players": 600, "fixtures": 380,
        "entry_id": 99, "history_events": 1,
    }
    assert all(item["passed"] for item in checks)


def test_fpl_bundle_rejects_partial_fixture_payload():
    boot, fixtures, entry, history = _fpl_bundle()
    with pytest.raises(ValueError, match="fixtures_380"):
        validate_bundle(boot, fixtures[:-1], entry, history, 99)


def test_odds_csv_requires_matches_and_real_odds():
    raw = ("Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,B365H,B365D,B365A\n"
           "E0,22/08/2026,15:00,Arsenal,Chelsea,2,1,H,1.80,3.60,4.50\n").encode()
    rows, quality, checks = parse_csv(raw)
    assert rows[0]["HomeTeam"] == "Arsenal"
    assert quality["matches_with_odds"] == 1
    assert all(item["passed"] for item in checks)


def test_odds_html_or_header_drift_is_quarantined():
    with pytest.raises(ValueError, match="sin columnas"):
        parse_csv(b"<html>300 Multiple Choices</html>")


def _event(event_id: int, local_id: int) -> dict:
    return {"id": event_id, "eventId": local_id, "minute": 1,
            "type": {"displayName": "Pass"}, "x": 1, "y": 2}


def test_whoscored_allows_reused_id_but_not_duplicate_pair():
    events = [_event(value, value) for value in range(1, 1001)]
    events[-1]["id"] = 1  # WhoScored sí reutiliza id; eventId lo desambigua.
    data = {"matchId": 42, "matchCentreData": {
        "statusCode": 6, "home": {"name": "A"}, "away": {"name": "B"},
        "events": events,
    }}
    quality = validate_match(data)
    assert quality["source_events"] == 1000
    assert quality["duplicate_ws_event_ids"] == 1
    events[-1]["eventId"] = 1
    with pytest.raises(ValueError, match="duplicados"):
        validate_match(data)


def test_whoscored_schedule_contract_detects_missing_match():
    rows = [{"game_id": value, "status": 6 if value <= 9 else 1}
            for value in range(1, 381)]
    quality, checks = validate_schedule(rows)
    assert quality["completed_matches"] == 9
    assert all(item["passed"] for item in checks)
    with pytest.raises(ValueError, match="schedule_380"):
        validate_schedule(rows[:-1])


def test_whoscored_calendar_and_monthly_payload_are_normalized_without_soccerdata():
    calendar = {"stageId": 25544, "mask": {
        "2026": {"7": {"21": 1}, "8": {"4": 1}},
        "2027": {"0": {"2": 1}, "4": {"30": 1}},
    }}
    assert calendar_months(calendar, "2026-27") == ["202608", "202609", "202701", "202705"]
    monthly = [{"tournaments": [{"matches": [{
        "id": 1983546, "startTimeUtc": "2026-08-22T11:30:00",
        "homeTeamName": "Arsenal", "awayTeamName": "Coventry", "status": 6,
    }]}]}]
    rows = normalize_schedule_rows(monthly + monthly)
    assert rows == [{
        "id": 1983546, "game_id": 1983546,
        "startTimeUtc": "2026-08-22T11:30:00", "date": "2026-08-22T11:30:00",
        "homeTeamName": "Arsenal", "home_team": "Arsenal",
        "awayTeamName": "Coventry", "away_team": "Coventry", "status": 6,
    }]


def test_collector_cli_and_force_audit_contract():
    parsed = parser().parse_args([
        "collect", "events", "--force", "--actor", "test",
        "--reason", "replay", "--idempotency-key", "events:replay:1",
    ])
    assert parsed.command == "collect"
    assert parsed.source == "events"
    assert parsed.force is True


def test_collector_config_rejects_unbounded_event_batch(tmp_path: Path):
    with pytest.raises(ValueError, match="EVENT_BATCH_SIZE"):
        RuntimeConfig(
            collector_event_batch_size=51,
            ops_db=tmp_path / "ops.db", artifact_root=tmp_path / "artifacts",
            host_probe_path=tmp_path / "probe.json", lock_path=tmp_path / "tick.lock",
            collector_lock_path=tmp_path / "collector.lock",
            collector_root=tmp_path / "collector", collector_browser_path=tmp_path / "chrome",
        ).validate()


def test_failed_source_respects_cadence_from_last_attempt():
    now = datetime(2026, 8, 24, tzinfo=timezone.utc)
    failed = {
        "last_status": "failed", "last_success_at": None,
        "last_attempt_at": now - timedelta(minutes=15),
    }
    assert cursor_is_due(failed, 6 * 3600, now=now) is False
    failed["last_attempt_at"] = now - timedelta(hours=6)
    assert cursor_is_due(failed, 6 * 3600, now=now) is True
    assert cursor_is_due(failed, 6 * 3600, now=now, force=True) is True


def test_postgres_data_service_migration_has_queryable_contract():
    assert latest_version() == 2
    sql = (MIGRATIONS / "002_autonomous_data_service.sql").read_text().lower()
    for table in (
        "raw.ingestion_runs", "raw.source_cursors", "raw.source_artifacts",
        "analytics.fpl_player_observations", "analytics.fpl_fixture_observations",
        "analytics.match_odds_observations", "analytics.whoscored_matches",
        "analytics.whoscored_events", "ops.v_data_source_health",
    ):
        assert table in sql


def test_data_artifacts_never_contain_secrets_in_contract():
    migration = (MIGRATIONS / "002_autonomous_data_service.sql").read_text().lower()
    assert "cookie" not in migration
    assert "password" not in migration
    assert "authorization" not in migration


def test_release_sha_does_not_invalidate_engine_dependency_layers():
    dockerfile = Path("deploy/docker/engine.Dockerfile").read_text()
    assert dockerfile.index("RUN python -m pip install") < dockerfile.index(
        "ARG MOVA_GIT_SHA=unknown"
    )
