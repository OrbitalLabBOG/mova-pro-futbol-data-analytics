from __future__ import annotations

import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pandas as pd

from mova_fpl.analytics.drift import assess_drift
from mova_fpl.analytics.metrics import COMPONENTS, evaluate_gameweek
from mova_fpl.analytics.market import build_context, canonical_team
from mova_fpl.ops.analytics_store import prometheus, publish_status, read_status
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


def test_analytics_defaults_match_approved_decision_models():
    config = RuntimeConfig()
    assert config.analytics_minutes_version == "1.1.0"
    assert config.analytics_points_version == "1.1.0"


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
        analytics_root=tmp_path / "analytics", postgres_credential_file=tmp_path / "missing",
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
        with urllib.request.urlopen(base + "/metrics", timeout=2) as response:
            metrics = response.read().decode()
            assert "mova_analytics_service_up 1" in metrics
            assert "mova_agent_budget_within_limit" in metrics
            assert "mova_model_bundle_pointer_present 0" in metrics
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
