from __future__ import annotations

import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pandas as pd

import mova_fpl.analytics.projection as projection_module
import mova_fpl.ops.analytics_service as analytics_service_module
from mova_fpl.analytics.drift import assess_drift
from mova_fpl.analytics.metrics import COMPONENTS, evaluate_gameweek
from mova_fpl.analytics.market import build_context, canonical_team
from mova_fpl.ops.analytics_store import prometheus, publish_status, read_status
from mova_fpl.ops.analytics_service import AnalyticsService
from mova_fpl.ops.api import make_handler
from mova_fpl.ops.cli import parser
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB
from mova_fpl.rules import get as get_rules


def _components(appearance: float) -> dict:
    return {name: appearance if name == "pts_aparicion" else 0.0 for name in COMPONENTS}


def test_gameweek_scorecard_reconciles_points_minutes_and_components():
    predictions = pd.DataFrame([
        {"element": 1, "position": "DEF", "xp": 6.0, "p_play": .9, "p_60": .8,
         "components": _components(2.0)},
        {"element": 2, "position": "MID", "xp": 2.0, "p_play": .5, "p_60": .3,
         "components": _components(1.0)},
    ])
    actual = pd.DataFrame([
        {"element": 1, "total_points": 6, "minutes": 90,
         "stats": {"total_points": 6, "minutes": 90, "clean_sheets": 1}},
        {"element": 2, "total_points": 0, "minutes": 0,
         "stats": {"total_points": 0, "minutes": 0}},
    ])
    result = evaluate_gameweek(predictions, actual, get_rules("2026-27").SCORING)
    metrics = result["metrics"]
    assert metrics["schema"] == "mova-model-scorecard-v1"
    assert metrics["sample_size"] == 2
    assert metrics["coverage"]["matched_players"] == 2
    assert metrics["points"]["predicted_total"] == 8
    assert metrics["points"]["actual_total"] == 6
    assert 0 <= metrics["minutes"]["play_brier"] <= 1
    assert {item["component"] for item in result["components"]} == set(COMPONENTS)


def test_gameweek_scorecard_accepts_goalkeeper_alias_and_canonical_position():
    for position in ("GK", "GKP"):
        predictions = pd.DataFrame([
            {"element": 1, "position": position, "xp": 2.0, "p_play": .9, "p_60": .8,
             "components": _components(2.0)},
        ])
        actual = pd.DataFrame([
            {"element": 1, "total_points": 2, "minutes": 90,
             "stats": {"total_points": 2, "minutes": 90}},
        ])

        result = evaluate_gameweek(predictions, actual, get_rules("2026-27").SCORING)

        assert result["metrics"]["coverage"]["matched_players"] == 1
        assert result["metrics"]["points"]["actual_total"] == 2


def test_drift_requires_history_then_exposes_reasons():
    metrics = {"points": {"mae": 3.0, "rmse": 4.0, "spearman": .1,
                           "relative_bias": .25},
               "minutes": {"play_ece": .09, "p60_ece": .11},
               "clean_sheet": {"brier": .25}}
    assert assess_drift(metrics, [metrics] * 5)["status"] == "insufficient"
    references = [{"points": {"mae": 1.5, "rmse": 2.0, "spearman": .5},
                   "minutes": {}, "clean_sheet": {}} for _ in range(6)]
    drift = assess_drift(metrics, references)
    assert drift["status"] == "alert"
    assert {item["code"] for item in drift["reasons"]} >= {
        "absolute_relative_bias", "mae_deterioration", "spearman_drop"
    }


def test_analytics_snapshot_and_prometheus_contract(tmp_path: Path):
    config = RuntimeConfig(analytics_root=tmp_path / "analytics")
    payload = {
        "schema": "mova-analytics-service-status-v1", "status": "healthy",
        "latest_scorecards": [{"season": "2026-27", "gw": 1, "variant": "baseline",
                               "drift_status": "healthy", "metrics": {
                                   "points": {"mae": 2.5}, "minutes": {"play_ece": .04},
                                   "clean_sheet": {"brier": .18}}}],
    }
    publish_status(config, payload)
    assert read_status(config) == payload
    text = prometheus(payload)
    assert 'mova_model_points_mae{season="2026-27",gw="1",variant="baseline"} 2.5' in text
    assert "mova_analytics_service_up 1" in text


def test_analytics_cli_is_agent_operable():
    assert parser().parse_args(["analytics", "run"]).analytics_command == "run"
    parsed = parser().parse_args(["analytics", "status", "--limit", "10"])
    assert parsed.analytics_command == "status" and parsed.limit == 10
    review = parser().parse_args([
        "review", "gw", "--package", "closeout.json", "--actor", "julian",
        "--reason", "cerrar GW1", "--idempotency-key", "gw1:closeout:v1",
    ])
    assert review.review_command == "gw"
    review_status = parser().parse_args(["review", "status", "--gw", "1"])
    assert review_status.review_command == "status" and review_status.gw == 1
    release = parser().parse_args([
        "improve", "release", "promote", "--release-id", "release_test",
        "--actor", "codex", "--reason", "shadow aprobado",
        "--idempotency-key", "release:test:promote",
    ])
    assert release.improve_command == "release"
    assert release.release_command == "promote"


def test_successful_analytics_replay_resolves_prior_failure_incident(
    tmp_path: Path, monkeypatch,
):
    config = RuntimeConfig(
        ops_db=tmp_path / "ops.db", analytics_root=tmp_path / "analytics",
        analytics_lock_path=tmp_path / "analytics.lock",
    )
    monkeypatch.setattr(RuntimeConfig, "validate", lambda self: None)
    monkeypatch.setattr(RuntimeConfig, "validate_postgres", lambda self: None)
    db = OpsDB(config.ops_db, enforce_version=False)
    db.migrate()
    key = "analytics:recovered"
    job_id, _ = db.start_job("model_analytics", key, "corr_recovered")
    db.finish_job(job_id, "completed")
    db.open_incident_once("P2", "Analytics service MOVA falló")

    result = AnalyticsService(config, db).run(
        actor="test", reason="replay confirmado", idempotency_key=key,
    )

    assert result == {"status": "reused", "job_id": job_id}
    with db.connect(readonly=True) as con:
        incident = con.execute(
            "SELECT status,resolution FROM incidents "
            "WHERE title='Analytics service MOVA falló'"
        ).fetchone()
    assert incident["status"] == "resolved"
    assert job_id in incident["resolution"]


def test_analytics_defaults_match_approved_decision_models():
    config = RuntimeConfig()
    assert config.analytics_minutes_version == "1.1.0"
    assert config.analytics_points_version == "1.1.0"


def test_project_snapshot_appends_closed_current_season_state(monkeypatch):
    previous = pd.DataFrame([{"season": "2025-26", "gw": 38, "element": 1}])
    current = pd.DataFrame([{"season": "2026-27", "gw": 1, "element": 1}])
    roster = pd.DataFrame([{
        "element": 1, "fixture": 301, "player_key": "player",
        "name": "Player", "position": "MID", "team": "A",
        "opponent_team": 2, "disponibilidad": 1.0, "estado": "a",
    }])
    quality = {"rows": 1, "players": 1, "gws": [1],
               "skipped_missing_current_catalog": 0,
               "skipped_historical_team_mismatch": 0,
               "repaired_historical_team_mismatch": 0, "duplicate_keys": 0}

    class FakeStore:
        def as_of(self, season, gw):
            assert (season, gw) == ("2025-26", 39)
            return previous

    monkeypatch.setattr(projection_module, "Store", FakeStore)
    monkeypatch.setattr(projection_module.live, "roster", lambda *_args: roster)
    monkeypatch.setattr(projection_module.live, "closed_history",
                        lambda *_args, **_kwargs: (current, quality))
    monkeypatch.setattr(projection_module.live, "teams", lambda _boot: {1: "A", 2: "B"})
    monkeypatch.setattr(projection_module.live, "team_schedule",
                        lambda *_args: {("A", 2): 1})
    monkeypatch.setattr(projection_module, "load", lambda *_args: object())

    def fake_projection(history, *_args, **_kwargs):
        assert history[["season", "gw"]].to_dict("records") == [
            {"season": "2025-26", "gw": 38},
            {"season": "2026-27", "gw": 1},
        ]
        detail = pd.DataFrame([{
            "element": 1, "xp": 4.0, "xp_sd": 1.5,
            "p_juega": .9, "p_60": .8, "p_porteria_cero": .2,
            **{name: (2.0 if name == "pts_aparicion" else .2) for name in COMPONENTS},
        }])
        return None, detail

    monkeypatch.setattr(projection_module, "points_projection", fake_projection)
    result = projection_module.project_snapshot(
        boot={}, fixtures=[], season="2026-27", gw=2,
        minutes_version="1.1.0", points_version="1.1.0",
        event_history={1: {"elements": []}}, element_summaries={},
    )

    assert result["versions"]["projection_contract"] == "model-analytics-v2"
    assert result["history"]["state"] == "append_closed"
    assert result["history"]["previous_rows"] == 1
    assert result["history"]["current"]["rows"] == 1
    assert result["history"]["total_rows"] == 2


def test_ops_db_finds_latest_valid_snapshot_for_event(tmp_path: Path):
    db = OpsDB(tmp_path / "ops.db", enforce_version=False)
    db.migrate()
    cycle = db.upsert_cycle(
        "2026-27", 3, "2026-09-04T17:30:00Z", phase="wide",
    )
    job_id, _ = db.start_job("tick", "tick:test:history", "corr_history")
    db.bind_job_cycle(job_id, cycle)
    snapshot_id = db.add_snapshot(
        job_id=job_id, cycle_id=cycle, source_name="fpl_official",
        captured_at="2026-09-04T05:00:00+00:00",
        artifact_path=str(tmp_path / "snapshot"), manifest_sha256="a" * 64,
        payload_sha256="b" * 64, freshness_seconds=0,
        quality_status="valid", quality={"history_state": "append_closed"},
    )

    observed = db.latest_snapshot_for_event("2026-27", 3)

    assert observed is not None
    assert observed["snapshot_id"] == snapshot_id
    assert db.latest_snapshot_for_event("2026-27", 4) is None


def test_analytics_service_projects_from_hash_bound_tick_snapshot(
    tmp_path: Path, monkeypatch,
):
    from datetime import datetime, timezone

    from mova_fpl.data.snapshot import capture_bytes
    from mova_fpl.ops.collector.contracts import sha256_bytes

    teams = [{"id": i, "name": f"T{i}", "short_name": f"T{i}"}
             for i in range(1, 21)]
    boot = {
        "teams": teams,
        "events": [
            {"id": 1, "deadline_time": "2026-08-28T17:30:00Z",
             "finished": True, "data_checked": True},
            {"id": 2, "deadline_time": "2026-09-04T17:30:00Z",
             "finished": False, "data_checked": False, "is_next": True},
        ],
        "elements": [{
            "id": 1, "first_name": "Test", "second_name": "Player",
            "web_name": "Player", "team": 1, "element_type": 3,
            "now_cost": 55, "status": "a",
        }],
    }
    fixtures = [{
        "id": 100 + i, "event": 2, "team_h": i, "team_a": i + 10,
        "kickoff_time": "2026-09-05T14:00:00Z",
    } for i in range(1, 11)]
    fixtures.append({
        "id": 91, "event": 1, "team_h": 1, "team_a": 2,
        "team_h_score": 1, "team_a_score": 0,
        "kickoff_time": "2026-08-29T14:00:00Z",
    })
    event = {"elements": [{
        "id": 1, "stats": {"minutes": 90, "total_points": 6},
        "explain": [{"fixture": 91, "stats": []}],
    }]}
    boot_raw = json.dumps(boot).encode()
    fixtures_raw = json.dumps(fixtures).encode()
    snapshot_path, _ = capture_bytes(
        "2026-27", 2, tmp_path / "snapshots", boot_raw, fixtures_raw,
        event_raw={1: json.dumps(event).encode()},
        captured_at="2026-09-04T10:00:00+00:00",
    )

    config = RuntimeConfig(
        ops_db=tmp_path / "ops.db", artifact_root=tmp_path / "artifacts",
        analytics_root=tmp_path / "analytics",
    )
    db = OpsDB(config.ops_db, enforce_version=False)
    db.migrate()
    cycle = db.upsert_cycle(
        "2026-27", 2, "2026-09-04T17:30:00Z", phase="wide",
    )
    job_id, _ = db.start_job("tick", "tick:test:analytics", "corr_analytics")
    db.bind_job_cycle(job_id, cycle)
    manifest_body = (snapshot_path / "manifest.json").read_bytes()
    db.add_snapshot(
        job_id=job_id, cycle_id=cycle, source_name="fpl_official",
        captured_at="2026-09-04T10:00:00+00:00",
        artifact_path=str(snapshot_path), manifest_sha256=sha256_bytes(manifest_body),
        payload_sha256="c" * 64, freshness_seconds=0,
        quality_status="valid", quality={},
    )
    raw_path = tmp_path / "raw"
    raw_path.mkdir()
    (raw_path / "bootstrap-static.json").write_bytes(boot_raw)
    (raw_path / "fixtures.json").write_bytes(fixtures_raw)

    class FakeAnalyticsStore:
        def latest_fpl_artifact(self):
            return {
                "artifact_id": "artifact_test", "artifact_path": str(raw_path),
                "observed_at": datetime(2026, 9, 4, 10, tzinfo=timezone.utc),
            }

        def projection_by_key(self, _key):
            return None

        def save_projection(self, **_kwargs):
            return "projection_test", False

        def market_context(self, **_kwargs):
            return {"artifact_id": None, "context": [], "quality": {
                "coverage_ratio": 0.0, "minimum_bookmakers": 0,
            }}

    observed = {}

    def fake_project_snapshot(**kwargs):
        observed.update(kwargs)
        return {
            "rows": [],
            "versions": {"minutes": "1.1.0", "points": "1.1.0",
                         "projection_contract": "model-analytics-v2",
                         "history_state": "append_closed"},
            "code_git_sha": "test",
            "history": {"state": "append_closed", "current": {"gws": [1]}},
        }

    monkeypatch.setattr(analytics_service_module, "project_snapshot", fake_project_snapshot)
    monkeypatch.setattr(
        "mova_fpl.ops.model_release.resolve_active_model_bundle",
        lambda *_args: {"source": "defaults", "release_id": None, "models": {
            "minutes": {"version": "1.1.0"}, "points": {"version": "1.1.0"},
        }},
    )
    service = AnalyticsService(config, db)
    service.store = FakeAnalyticsStore()
    result = service.project(datetime(2026, 9, 4, 11, tzinfo=timezone.utc))

    assert result["status"] == "completed"
    assert result["history_input"]["settled_gws"] == [1]
    assert observed["event_history"][1] == event
    assert observed["element_summaries"] == {}


def test_market_context_requires_and_preserves_bookmaker_consensus():
    assert canonical_team("Leeds") == canonical_team("Leeds United")
    fixtures = [{"fixture": 42, "kickoff_time": "2026-08-29T14:00:00Z",
                 "home_team": "Man City", "away_team": "Arsenal"}]
    rows = []
    for book in range(5):
        common = {"provider_event_id": "event-1", "commence_time": "2026-08-29T14:00:00Z",
                  "home_team": "Manchester City", "away_team": "Arsenal",
                  "bookmaker_key": f"book-{book}"}
        rows.extend([
            {**common, "market_key": "h2h", "outcome_name": "Manchester City",
             "price": 1.8, "point": None},
            {**common, "market_key": "h2h", "outcome_name": "Draw",
             "price": 3.6, "point": None},
            {**common, "market_key": "h2h", "outcome_name": "Arsenal",
             "price": 4.5, "point": None},
            {**common, "market_key": "totals", "outcome_name": "Over",
             "price": 1.9, "point": 2.5},
            {**common, "market_key": "totals", "outcome_name": "Under",
             "price": 2.0, "point": 2.5},
        ])
    context, quality = build_context(fixtures, rows)
    assert quality["coverage_ratio"] == 1.0
    assert quality["minimum_bookmakers"] == 5
    assert context[0]["fixture"] == 42
    assert context[0]["lambda_home"] > context[0]["lambda_away"]


def test_read_only_api_exposes_analytics_and_prometheus(tmp_path: Path):
    config = RuntimeConfig(
        ops_db=tmp_path / "ops.db", artifact_root=tmp_path / "artifacts",
        analytics_root=tmp_path / "analytics",
        research_root=tmp_path / "artifacts" / "research",
        postgres_credential_file=tmp_path / "missing",
    )
    db = OpsDB(config.ops_db, enforce_version=False)
    db.migrate()
    payload = {"schema": "mova-analytics-service-status-v1", "status": "healthy",
               "latest_scorecards": [], "latest_projection_batches": []}
    publish_status(config, payload)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(db, config))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        with urllib.request.urlopen(base + "/api/v1/analytics", timeout=2) as response:
            assert json.load(response)["schema"] == "mova-analytics-service-status-v1"
        with urllib.request.urlopen(base + "/api/v1/costs", timeout=2) as response:
            assert json.load(response)["schema"] == "mova-agent-cost-report-v1"
        with urllib.request.urlopen(base + "/api/v1/readiness", timeout=2) as response:
            readiness = json.load(response)
            assert readiness["schema"] == "mova-autonomy-readiness-v1"
            assert readiness["activation"]["promotion_is_automatic"] is False
        with urllib.request.urlopen(base + "/api/v1/harness-scorecard", timeout=2) as response:
            scorecard = json.load(response)
            assert scorecard["schema"] == "mova-harness-scorecard-v1"
            assert scorecard["authority"]["promotion_is_automatic"] is False
        with urllib.request.urlopen(base + "/api/v1/orchestration", timeout=2) as response:
            orchestration = json.load(response)
            assert orchestration["schema"] == "mova-orchestration-status-v1"
            assert orchestration["runtime_mutated"] is False
        with urllib.request.urlopen(base + "/api/v1/budget-overrun-events", timeout=2) as response:
            assert json.load(response)["items"] == []
        with urllib.request.urlopen(base + "/api/v1/agent-queue", timeout=2) as response:
            queue = json.load(response)
            assert queue["healthy"] is True
            assert queue["requests"] == 0
        with urllib.request.urlopen(base + "/metrics", timeout=2) as response:
            metrics = response.read().decode()
            assert "mova_analytics_service_up 1" in metrics
            assert "mova_agent_budget_within_limit" in metrics
            assert "mova_model_bundle_pointer_present 0" in metrics
            assert "mova_autonomy_readiness_up 1" in metrics
            assert "mova_harness_scorecard_up 1" in metrics
            assert "mova_orchestration_dependency_violations 0" in metrics
            assert "mova_agent_queue_healthy 1" in metrics
            assert "mova_agent_queue_anomalies 0" in metrics
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
