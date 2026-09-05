from dataclasses import replace

import pytest

from mova_fpl.engine.season_value import CHIPS, SeasonValueModel
from mova_fpl.engine.state import State
from mova_fpl.rules.chips import ChipCatalogue, ChipUse, ChipWindow, validate_chip


def state(gw=1, end=3, used=(), chips=CHIPS):
    return State(season="2026-27", gw=gw, candidates=(), chips_used=used,
                 chips=ChipCatalogue(chips, (ChipWindow("test", 1, end),)))


def model(values):
    return SeasonValueModel().fit([
        {"season": "2024-25", "values": {c: v.get(c, 0.) for c in CHIPS}}
        for v in values
    ], target_season="2026-27")


def test_joint_inventory_reserves_best_chip_and_uses_other_slot():
    m = model([{"bench_boost": 10, "triple_captain": 1}])
    s = state(end=2, chips=("bench_boost", "triple_captain"))
    chip, evidence = m.choose(s, {"bench_boost": 9, "triple_captain": 5})
    assert chip == "triple_captain"
    assert evidence["q_values"][chip] == 15
    assert evidence["q_values"]["bench_boost"] == 10


def test_expiry_does_not_spend_two_chips_or_carry_expired_value():
    m = model([{"bench_boost": 100, "triple_captain": 100}])
    s = state(gw=3)
    chip, e = m.choose(s, {"bench_boost": 2, "triple_captain": 4})
    assert chip == "triple_captain"
    assert e["hold_value"] == 0
    assert e["q_values"][chip] == 4
    assert not validate_chip(chip, s.gw, s.chips_used, s.chips)


def test_future_uncertainty_is_not_known_at_current_decision():
    m = model([{"triple_captain": 0}, {"triple_captain": 10}])
    s = state(end=2, chips=("triple_captain",))
    chip, e = m.choose(s, {"triple_captain": 6})
    assert e["hold_value"] == 5
    assert chip == "triple_captain"
    # Clairvoyant E[max(6, future)] would be 8; attainable current action is 6.
    assert e["q_values"][chip] == 6


def test_joint_samples_preserve_correlated_chip_opportunities():
    s = state(end=2, chips=("bench_boost", "triple_captain"))
    paired = model([{"bench_boost": 10}, {"triple_captain": 10}])
    correlated = model([{"bench_boost": 10, "triple_captain": 10}, {}])
    assert paired.choose(s, {})[1]["hold_value"] == 10
    assert correlated.choose(s, {})[1]["hold_value"] == 5


def test_unknown_schedule_is_not_all_blank():
    m = model([{"free_hit": 2}])
    s = state(end=3)
    a = m.choose(s, {})[1]["hold_value"]
    b = m.choose(replace(s, schedule={("A", 1): 1}), {})[1]["hold_value"]
    assert a == b


def test_illegal_exhausted_chip_is_never_offered():
    m = model([{"bench_boost": 1}])
    s = state(gw=3, used=(ChipUse(1, "bench_boost"),))
    chip, e = m.choose(s, {"bench_boost": 1000})
    assert chip is None and "bench_boost" not in e["q_values"]


def test_fit_and_inference_reject_future_training():
    with pytest.raises(ValueError, match="prior seasons"):
        SeasonValueModel().fit([{"season": "2026-27"}], target_season="2026-27")
    with pytest.raises(ValueError, match="future season"):
        model([{}]).choose(replace(state(), season="2024-25"), {})
