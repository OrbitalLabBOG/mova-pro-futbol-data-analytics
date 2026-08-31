from __future__ import annotations

import json
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mova_fpl.data import sources
from mova_fpl.ops.cli import parser
from mova_fpl.ops.collector.fpl import validate_bundle
from mova_fpl.ops.collector.odds import parse_payload
from mova_fpl.ops.collector.odds_policy import plan_collection
from mova_fpl.ops.collector.whoscored import (
    calendar_months,
    normalize_schedule_rows,
    validate_match,
    validate_schedule,
)
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.collector.store import cursor_is_due, publish_coverage, read_coverage
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
        "entry_id": 99, "history_events": 1, "players_with_news": 0,
        "players_flagged": 0,
    }
    assert all(item["passed"] for item in checks)


def test_fpl_bundle_rejects_partial_fixture_payload():
    boot, fixtures, entry, history = _fpl_bundle()
    with pytest.raises(ValueError, match="fixtures_380"):
        validate_bundle(boot, fixtures[:-1], entry, history, 99)


def _odds_payload() -> bytes:
    markets = [
        {"key": "h2h", "last_update": "2026-08-23T10:00:00Z", "outcomes": [
            {"name": "Arsenal", "price": 1.8}, {"name": "Draw", "price": 3.6},
            {"name": "Chelsea", "price": 4.5},
        ]},
        {"key": "totals", "last_update": "2026-08-23T10:00:00Z", "outcomes": [
            {"name": "Over", "price": 1.91, "point": 2.5},
            {"name": "Under", "price": 1.95, "point": 2.5},
        ]},
    ]
    return json.dumps([{
        "id": "event-1", "sport_key": "soccer_epl",
        "commence_time": "2026-08-24T19:00:00Z",
        "home_team": "Arsenal", "away_team": "Chelsea",
        "bookmakers": [
            {"key": f"book-{index}", "title": f"Book {index}",
             "last_update": "2026-08-23T10:00:00Z", "markets": markets}
            for index in range(5)
        ],
    }]).encode()


def test_market_odds_preserve_every_book_market_outcome():
    headers = {"x-requests-used": "8", "x-requests-remaining": "492",
               "x-requests-last": "4"}
    rows, quality, checks = parse_payload(_odds_payload(), headers)
    assert len(rows) == 25
    assert len({row["observation_key"] for row in rows}) == 25
    assert rows[0]["home_team"] == "Arsenal"
    assert quality["bookmakers"] == 5
    assert quality["h2h_coverage_ratio"] == 1.0
    assert quality["quota"] == {"used": 8, "remaining": 492, "last_cost": 4}
    assert all(item["passed"] for item in checks)


def test_market_odds_error_payload_is_quarantined():
    with pytest.raises(ValueError, match="no devolvió JSON"):
        parse_payload(b"<html>upstream error</html>")
    with pytest.raises(ValueError, match="objeto de error"):
        parse_payload(b'{"message":"OUT_OF_USAGE_CREDITS"}')


def test_market_odds_network_error_never_exposes_api_key(monkeypatch):
    secret = "test-secret-that-must-never-appear"

    def fail(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)

    monkeypatch.setattr(sources.urllib.request, "urlopen", fail)
    monkeypatch.setattr(sources.time, "sleep", lambda _: None)
    with pytest.raises(OSError) as error:
        sources.fetch_market_odds(secret)
    assert secret not in str(error.value)
    assert "apiKey" not in str(error.value)


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


def test_collector_config_caps_odds_request_cost(tmp_path: Path):
    with pytest.raises(ValueError, match="4 créditos"):
        RuntimeConfig(
            odds_api_regions="uk,eu,us", odds_api_markets="h2h,totals",
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


def test_odds_policy_spends_two_credits_far_from_deadline():
    now = datetime(2026, 8, 24, tzinfo=timezone.utc)
    plan = plan_collection(
        RuntimeConfig(), now=now,
        deadline={"event_id": 2, "deadline_time": now + timedelta(days=5)},
        cursor=None,
    )
    assert plan.due is True
    assert plan.tier == "baseline"
    assert plan.regions == "uk"
    assert plan.planned_cost == 2
    assert plan.cadence_seconds == 24 * 3600


def test_odds_policy_takes_one_full_checkpoint_and_preserves_reserves():
    now = datetime(2026, 8, 24, tzinfo=timezone.utc)
    deadline = {"event_id": 2, "deadline_time": now + timedelta(hours=5)}
    initial = plan_collection(RuntimeConfig(), now=now, deadline=deadline, cursor=None)
    assert initial.due is True
    assert initial.tier == "deadline"
    assert initial.regions == "uk,eu"
    assert initial.planned_cost == 4

    cursor = {
        "last_status": "completed", "last_success_at": now - timedelta(days=1),
        "detail": {"quality": {"quota": {"remaining": 492},
                               "policy": initial.as_dict()}},
    }
    duplicate = plan_collection(RuntimeConfig(), now=now, deadline=deadline, cursor=cursor)
    assert duplicate.due is False
    assert duplicate.reason == "deadline_checkpoint_already_collected"

    low = {"last_status": "completed", "last_success_at": now - timedelta(days=2),
           "detail": {"quality": {"quota": {"remaining": 74}}}}
    guarded = plan_collection(
        RuntimeConfig(), now=now,
        deadline={"event_id": 3, "deadline_time": now + timedelta(hours=2)}, cursor=low,
    )
    assert guarded.due is False
    assert guarded.reason == "hard_reserve_final_hour_only"


def test_odds_policy_force_never_bypasses_quota_guard():
    now = datetime(2026, 8, 24, tzinfo=timezone.utc)
    cursor = {"detail": {"quality": {"quota": {"remaining": 1}}}}
    plan = plan_collection(
        RuntimeConfig(), now=now,
        deadline={"event_id": 2, "deadline_time": now + timedelta(minutes=30)},
        cursor=cursor, force=True,
    )
    assert plan.due is False
    assert plan.reason == "insufficient_provider_quota"


def test_postgres_data_service_migration_has_queryable_contract():
    assert latest_version() == 21
    sql = "\n".join(path.read_text().lower() for path in sorted(MIGRATIONS.glob("*.sql")))
    for table in (
        "raw.ingestion_runs", "raw.source_cursors", "raw.source_artifacts",
        "analytics.fpl_player_observations", "analytics.fpl_fixture_observations",
        "analytics.fpl_team_observations", "analytics.fpl_event_observations",
        "analytics.fpl_event_live_observations", "analytics.model_projection_batches",
        "analytics.model_evaluation_runs", "analytics.model_evaluation_components",
        "analytics.match_odds_observations", "analytics.whoscored_matches",
        "analytics.market_odds_observations", "analytics.whoscored_events",
        "ops.v_data_source_health",
        "agent.decision_envelopes", "agent.decision_candidates",
        "agent.decision_validation_checks",
        "agent.decision_deliberations", "agent.decision_deliberation_risks",
        "agent.execution_plans", "agent.execution_preflight_checks",
    ):
        assert table in sql


def test_data_artifacts_never_contain_secrets_in_contract():
    migration = "\n".join(path.read_text().lower() for path in sorted(MIGRATIONS.glob("*.sql")))
    assert "cookie" not in migration
    assert "password" not in migration
    assert "authorization" not in migration


def test_coverage_snapshot_is_available_to_unprivileged_api(tmp_path: Path):
    config = RuntimeConfig(collector_root=tmp_path / "collector")
    payload = {"schema": "mova-data-service-coverage-v1", "status": "complete"}
    publish_coverage(config, payload)
    assert read_coverage(config) == payload


def test_release_sha_does_not_invalidate_engine_dependency_layers():
    dockerfile = Path("deploy/docker/engine.Dockerfile").read_text()
    assert dockerfile.index("RUN python -m pip install") < dockerfile.index(
        "ARG MOVA_GIT_SHA=unknown"
    )


def test_versioned_decision_packages_are_in_engine_build_context():
    ignored = {
        line.strip() for line in Path(".dockerignore").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert "decisions" not in ignored
    assert "COPY decisions /app/decisions" in Path(
        "deploy/docker/engine.Dockerfile"
    ).read_text()
