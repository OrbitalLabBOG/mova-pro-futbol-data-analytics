"""Contratos del laboratorio causal de horizonte largo."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from experiments.long_horizon.metrics import (
    normal_crps,
    paired_policy_bootstrap,
    paired_policy_influence,
)
from experiments.long_horizon.models import EventProxyGoalsModel
from experiments.long_horizon.event_h3 import summarize_development
from experiments.long_horizon.stochastic_recourse import _scenario_matrices
from experiments.long_horizon.terminal_value import POLICY_NAME, summarize as summarize_terminal
from experiments.long_horizon.discrete_uncertainty import (
    SUPPORT,
    discrete_metrics,
    knn_discrete_pmf,
    normal_discrete_pmf,
)
from mova_fpl.engine.discrete_uncertainty import (
    load_calibration_artifact,
    shadow_distribution,
    write_calibration_artifact,
)
from mova_fpl.engine.baselines import _prepara
from mova_fpl.models.features.minutes_features import FEATURES, build, build_targets
from mova_fpl.models.features.points_features import player_rates
from mova_fpl.models.goals import GoalsModel
from mova_fpl.rules import get as get_rules
from mova_fpl.engine.state import Candidate, State
from mova_fpl.rules.base import Position


def _minute_history() -> pd.DataFrame:
    return pd.DataFrame([
        {"player_key": key, "season": "2023-24", "gw": gw, "fixture": gw * 10 + element,
         "minutes": minutes, "starts": int(minutes >= 60), "value": 50,
         "position": position, "was_home": gw % 2, "element": element,
         "total_points": 2}
        for key, element, position in (("a", 1, "DEF"), ("b", 2, "MID"))
        for gw, minutes in ((1, 90), (2, 0), (3, 35), (4, 90))
    ])


def test_target_features_are_equivalent_to_training_builder_for_unique_players():
    history = _minute_history()
    target = pd.DataFrame([
        {"player_key": "a", "season": "2023-24", "gw": 5, "fixture": 51,
         "value": 51, "position": "DEF", "was_home": 1, "element": 1},
        {"player_key": "b", "season": "2023-24", "gw": 5, "fixture": 52,
         "value": 62, "position": "MID", "was_home": 0, "element": 2},
    ])
    old_target = target.assign(minutes=np.nan, starts=np.nan, total_points=np.nan)
    frame = pd.concat([history, old_target], ignore_index=True)
    frame["_objetivo"] = [False] * len(history) + [True] * len(target)
    expected = build(frame).query("_objetivo").set_index("element")[FEATURES]
    actual = build_targets(history, target).set_index("element")[FEATURES]
    assert np.allclose(expected, actual, equal_nan=True)


def test_two_targets_with_same_name_do_not_become_each_others_history():
    history = _minute_history().query("player_key == 'a'")
    target = pd.DataFrame([
        {"player_key": "a", "season": "2023-24", "gw": 5, "fixture": fixture,
         "value": 51, "position": "DEF", "was_home": home, "element": element}
        for fixture, home, element in ((51, 1, 1), (52, 0, 99))
    ])
    built = build_targets(history, target)
    assert built["n_prev"].tolist() == [4, 4]
    assert built["racha_ceros"].tolist() == [0, 0]


def test_event_weight_zero_reproduces_goals_model():
    rates = pd.DataFrame({"xg90": [0.4], "g90": [0.2], "xa90": [0.3], "a90": [0.1],
                          "threat90": [40.0], "creativity90": [30.0]})
    positions = pd.Series(["MID"])
    base = GoalsModel(definicion={"MID": 1.1}, creacion={"MID": 1.2})
    candidate = EventProxyGoalsModel(
        definicion={"MID": 1.1}, creacion={"MID": 1.2}, proxy_weight=0.0,
        threat_to_goal={"MID": 0.01}, creativity_to_assist={"MID": 0.01},
    )
    assert candidate.rate(rates, positions, "gol") == pytest.approx(
        base.rate(rates, positions, "gol"))
    assert candidate.rate(rates, positions, "asistencia") == pytest.approx(
        base.rate(rates, positions, "asistencia"))


def test_recency_weights_recent_appearances_more_than_old_ones():
    history = pd.DataFrame([
        {"player_key": "p", "season": "2023-24", "gw": 1, "fixture": 1,
         "minutes": 90, "position": "FWD", "goals_scored": 4},
        {"player_key": "p", "season": "2023-24", "gw": 2, "fixture": 2,
         "minutes": 90, "position": "FWD", "goals_scored": 0},
    ])
    plain = player_rates(history).loc["p", "g90"]
    recent = player_rates(history, half_life_appearances=1).loc["p", "g90"]
    assert plain == pytest.approx(2.0)
    assert recent < plain


def test_historical_rules_do_not_award_defcon_and_version_free_transfers():
    assert get_rules("2020-21").SCORING.defcon_thresholds == {}
    assert get_rules("2020-21").SQUAD["max_free_transfers"] == 2
    assert get_rules("2021-22").SCORING.defcon_thresholds == {}
    assert get_rules("2021-22").SQUAD["max_free_transfers"] == 2
    assert get_rules("2024-25").SQUAD["max_free_transfers"] == 5


def test_historical_baselines_exclude_assistant_manager_assets():
    results = pd.DataFrame([
        {"element": 1, "total_points": 6, "minutes": 90, "selected": 10,
         "value": 50, "position": "MID", "team": "A"},
        {"element": 2, "total_points": 12, "minutes": 0, "selected": 10,
         "value": 15, "position": "AM", "team": "A"},
    ])
    prepared = _prepara(results)
    assert prepared["element"].tolist() == [1]


def test_2024_25_roster_excludes_assistant_manager_assets(tmp_path):
    import sqlite3

    from mova_fpl.data.store import Store

    common = {"season": "2024-25", "gw": 38, "team": "A", "value": 50,
              "opponent_team": 2, "was_home": 1, "fixture": 380,
              "kickoff_time": "2025-05-25T15:00:00Z"}
    rows = [
        {**common, "element": 1, "player_key": "player", "name": "Player",
         "position": "MID"},
        {**common, "element": 2, "player_key": "manager", "name": "Manager",
         "position": "AM"},
    ]
    db = tmp_path / "canonical.db"
    with sqlite3.connect(db) as connection:
        pd.DataFrame(rows).to_sql("player_gameweek", connection, index=False)

    roster = Store(db).roster("2024-25", 38)
    assert not (roster["position"] == "AM").any()
    assert set(roster["position"].dropna()) <= {"GK", "GKP", "DEF", "MID", "FWD"}


def test_normal_crps_degenerates_to_absolute_error():
    assert normal_crps([3.0], [1.0], [0.0])[0] == pytest.approx(2.0)


def test_policy_bootstrap_is_paired_and_reproducible():
    baseline = pd.DataFrame({"season": ["a"] * 4, "gw": [1, 2, 3, 4],
                             "points": [50, 50, 50, 50]})
    candidate = baseline.assign(points=[51, 51, 51, 51])
    result = paired_policy_bootstrap(baseline, candidate, draws=100, block_size=2, seed=7)
    assert result["observed_by_season"] == {"a": 4.0}
    assert result["probability_positive"] == 1.0
    assert result["influence"]["by_season"]["a"]["through_penultimate_gw"] == 3.0


def test_policy_influence_exposes_a_single_gameweek_sign_reversal():
    baseline = pd.DataFrame({"season": ["a"] * 4 + ["b"] * 4,
                             "gw": [1, 2, 3, 4] * 2,
                             "points": [50] * 8})
    candidate = baseline.assign(points=[55, 55, 55, 14, 52, 52, 52, 52])

    result = paired_policy_influence(baseline, candidate)

    assert result["by_season"]["a"]["delta"] == -21
    assert result["by_season"]["a"]["through_penultimate_gw"] == 15
    assert result["by_season"]["a"]["worst_gw"] == {"gw": 4, "delta": -36.0}
    assert result["by_season"]["a"]["loss_reversal_by_one_gw"] is True
    assert result["loss_reversal_seasons"] == ["a"]
    assert result["leave_one_season_out_mean"] == {"a": 8.0, "b": -21.0}


def test_policy_influence_rejects_missing_pairs():
    baseline = pd.DataFrame({"season": ["a", "a"], "gw": [1, 2],
                             "points": [50, 50]})
    candidate = pd.DataFrame({"season": ["a"], "gw": [1], "points": [51]})

    with pytest.raises(ValueError, match="exactamente las mismas"):
        paired_policy_influence(baseline, candidate)


def test_terminal_value_challenger_requires_three_of_four_development_wins(tmp_path):
    records = []
    for season, delta in zip(("a", "b", "c", "d"), (1, 1, 1, -1)):
        for variant, points in (("season_fixture_h3", 50), (POLICY_NAME, 50 + delta)):
            records.append({
                "season": season, "variant": variant, "points": points,
                "gameweeks": [{"gw": 1, "points": points}],
            })
    manifest = {"experiment_id": "EXP-TEST", "source_sha256": "s",
                "dataset": {"sha256": "d"}}

    result = summarize_terminal(records, tmp_path, manifest)

    assert result["wins"] == result["required_wins"] == 3
    assert result["mean_delta"] > 0
    assert result["challenger_accepted"] is True
    assert result["selected_policy"] == POLICY_NAME


def test_recourse_scenarios_preserve_each_frozen_player_mean_exactly():
    candidates = tuple(
        Candidate(element=element, position=Position.MID, team=f"T{element}",
                  price=5.0, xp=3.0)
        for element in (1, 2)
    )
    mean = {5: {1: 3.0, 2: 2.0}, 6: {1: 2.52, 2: 1.68}}
    probabilities = np.zeros(len(SUPPORT), dtype=float)
    probabilities[np.flatnonzero(SUPPORT == 0)[0]] = 0.5
    probabilities[np.flatnonzero(SUPPORT == 6)[0]] = 0.5
    rows = {
        gw: {element: probabilities.tolist() for element in mean[gw]}
        for gw in mean
    }
    state = State(
        season="2026-27", gw=5, candidates=candidates,
        rules=get_rules("2026-27").SQUAD, horizon_xp=mean,
        horizon_pmf={"support": SUPPORT.tolist(), "rows": rows, "decay": 0.84},
    )
    scenarios = _scenario_matrices(state, count=6, seed=7)
    for gw, row in mean.items():
        for element, expected in row.items():
            observed = np.mean([scenario[gw][element] for scenario in scenarios])
            assert observed == pytest.approx(expected)


def test_event_h3_challenger_requires_two_wins_and_positive_mean(tmp_path):
    records = []
    totals = {
        "control_h3": [50, 50, 50],
        "season_fixture_h3": [51, 52, 53],
        "season_fixture_h3_events": [53, 51, 54],
    }
    for season_index, season in enumerate(("a", "b", "c")):
        for variant, points in totals.items():
            records.append({
                "season": season,
                "variant": variant,
                "points": points[season_index],
                "gameweeks": [{"gw": 1, "points": points[season_index]}],
            })
    manifest = {
        "experiment_id": "test",
        "source_sha256": "source",
        "dataset": {"sha256": "data"},
        "challenger_gate": "two wins and positive mean",
    }
    result = summarize_development(records, tmp_path, manifest)
    assert result["event_delta_vs_incumbent_by_season"] == {"a": 2, "b": -1, "c": 1}
    assert result["event_wins_vs_incumbent"] == 2
    assert result["event_mean_delta_vs_incumbent"] > 0
    assert result["selected_policy"] == "season_fixture_h3_events"


def test_event_h3_challenger_rejected_with_only_one_win(tmp_path):
    records = []
    totals = {
        "control_h3": [50, 50, 50],
        "season_fixture_h3": [51, 52, 53],
        "season_fixture_h3_events": [56, 51, 52],
    }
    for season_index, season in enumerate(("a", "b", "c")):
        for variant, points in totals.items():
            records.append({
                "season": season,
                "variant": variant,
                "points": points[season_index],
                "gameweeks": [{"gw": 1, "points": points[season_index]}],
            })
    manifest = {
        "experiment_id": "test",
        "source_sha256": "source",
        "dataset": {"sha256": "data"},
        "challenger_gate": "two wins and positive mean",
    }
    result = summarize_development(records, tmp_path, manifest)
    assert result["event_mean_delta_vs_incumbent"] > 0
    assert result["event_wins_vs_incumbent"] == 1
    assert result["selected_policy"] == "season_fixture_h3"


def test_discretized_normal_is_a_normalized_pmf():
    pmf = normal_discrete_pmf([0.0, 3.0], [1.0, 0.0])
    assert pmf.shape == (2, len(SUPPORT))
    assert pmf.sum(axis=1) == pytest.approx([1.0, 1.0])
    assert SUPPORT[pmf[1].argmax()] == 3


def test_knn_distribution_preserves_zero_inflation_and_position():
    calibration = pd.DataFrame({
        "position": ["GK"] * 4 + ["FWD"] * 4,
        "xp": [1.0] * 8,
        "xp_sd": [2.0] * 8,
        "n_fixtures": [1] * 8,
        "actual": [0, 0, 0, 1, 2, 5, 6, 8],
    })
    target = pd.DataFrame({
        "position": ["GK", "FWD"], "xp": [1.0, 1.0],
        "xp_sd": [2.0, 2.0], "n_fixtures": [1, 1],
    })
    pmf = knn_discrete_pmf(
        calibration, target, neighbors=4, prior_strength=0.0
    )
    zero = int(np.flatnonzero(SUPPORT == 0)[0])
    assert pmf.sum(axis=1) == pytest.approx([1.0, 1.0])
    assert pmf[0, zero] > pmf[1, zero]


def test_discrete_metrics_rewards_exact_distribution():
    actual = np.array([0, 2])
    pmf = np.zeros((2, len(SUPPORT)))
    pmf[0, int(np.flatnonzero(SUPPORT == 0)[0])] = 1.0
    pmf[1, int(np.flatnonzero(SUPPORT == 2)[0])] = 1.0
    metrics = discrete_metrics(actual, pmf)
    assert metrics["crps_discrete"] == pytest.approx(0.0)
    assert metrics["log_score"] == pytest.approx(0.0)
    assert metrics["coverage_90"] == 1.0


def test_discrete_calibration_artifact_is_hash_bound_and_pickle_free(tmp_path):
    calibration = pd.DataFrame({
        "position": ["GK", "GK", "FWD", "FWD"],
        "xp": [1.0, 2.0, 3.0, 4.0],
        "xp_sd": [1.0, 1.5, 2.0, 2.5],
        "n_fixtures": [1, 1, 1, 2],
        "actual": [0, 1, 2, 8],
    })
    path = tmp_path / "calibrator.npz"
    descriptor = write_calibration_artifact(
        path, calibration,
        metadata={"experiment_id": "exp", "selected_for_execution": False},
    )
    loaded, metadata = load_calibration_artifact(path, descriptor["sha256"])
    assert loaded.to_dict("list") == calibration.to_dict("list")
    assert metadata["schema"] == "mova-discrete-calibrator-v1"

    target = calibration.drop(columns="actual").assign(element=[1, 2, 3, 4])
    result = shadow_distribution(
        target, artifact_path=path, artifact_sha256=descriptor["sha256"], neighbors=2,
    )
    assert result["selected_for_execution"] is False
    assert result["optimization_mean_unchanged"] is True
    assert result["row_count"] == 4
    assert sum(result["rows"]["1"]["pmf"]) == pytest.approx(1.0)

    with pytest.raises(ValueError, match="SHA-256"):
        load_calibration_artifact(path, "0" * 64)
