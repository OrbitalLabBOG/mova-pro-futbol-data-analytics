"""Contratos del laboratorio causal de horizonte largo."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from experiments.long_horizon.metrics import normal_crps, paired_policy_bootstrap
from experiments.long_horizon.models import EventProxyGoalsModel
from mova_fpl.models.features.minutes_features import FEATURES, build, build_targets
from mova_fpl.models.features.points_features import player_rates
from mova_fpl.models.goals import GoalsModel
from mova_fpl.rules import get as get_rules


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
    assert get_rules("2021-22").SCORING.defcon_thresholds == {}
    assert get_rules("2021-22").SQUAD["max_free_transfers"] == 2
    assert get_rules("2024-25").SQUAD["max_free_transfers"] == 5


def test_normal_crps_degenerates_to_absolute_error():
    assert normal_crps([3.0], [1.0], [0.0])[0] == pytest.approx(2.0)


def test_policy_bootstrap_is_paired_and_reproducible():
    baseline = pd.DataFrame({"season": ["a"] * 4, "gw": [1, 2, 3, 4],
                             "points": [50, 50, 50, 50]})
    candidate = baseline.assign(points=[51, 51, 51, 51])
    result = paired_policy_bootstrap(baseline, candidate, draws=100, block_size=2, seed=7)
    assert result["observed_by_season"] == {"a": 4.0}
    assert result["probability_positive"] == 1.0
