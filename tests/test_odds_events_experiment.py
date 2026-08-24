import numpy as np
import pandas as pd

from experiments.odds_events.context import (
    build_event_factors,
    devig,
    infer_market_lambdas,
    load_opening_market,
    score_probabilities,
)
from experiments.odds_events.run import _weekly_bootstrap


def test_devig_sums_to_one():
    p = devig(1.80, 3.60, 4.80)
    assert np.isclose(p.sum(), 1.0)
    assert (p > 0).all()


def test_market_inversion_recovers_synthetic_lambdas():
    expected = score_probabilities(1.75, 0.95)
    home, away, error = infer_market_lambdas(expected[:3], expected[3])
    assert abs(home - 1.75) < 0.02
    assert abs(away - 0.95) < 0.02
    assert error < 1e-3


def test_poisson_probabilities_are_valid():
    p = score_probabilities(1.4, 1.1)
    assert np.isclose(p[:3].sum(), 1.0)
    assert (p > 0).all() and (p < 1).all()


def test_market_loader_never_uses_closing_columns(tmp_path):
    (tmp_path / "season-2526.csv").write_text(
        "Date,HomeTeam,AwayTeam,AvgH,AvgD,AvgA,Avg>2.5,Avg<2.5,AvgCH,AvgCD,AvgCA\n"
        "17/08/2025,Arsenal,Chelsea,2.0,3.0,4.0,1.8,2.2,99,99,1.01\n",
        encoding="utf-8",
    )
    market = load_opening_market(tmp_path, ("2025-26",))
    expected = devig(2.0, 3.0, 4.0)
    assert len(market) == 1
    assert np.isclose(market.loc[0, "p_home_market"], expected[0])
    assert np.isclose(market.loc[0, "p_away_market"], expected[2])


def test_event_state_updates_only_after_the_whole_gameweek():
    matches = pd.DataFrame([
        {"season": "2025-26", "gw": 1, "fixture": 1,
         "home_team": "A", "away_team": "B"},
        {"season": "2025-26", "gw": 1, "fixture": 2,
         "home_team": "A", "away_team": "C"},
        {"season": "2025-26", "gw": 2, "fixture": 3,
         "home_team": "A", "away_team": "B"},
    ])
    event_rows = []
    for fixture, home, away in ((1, "A", "B"), (2, "A", "C")):
        row = {"fixture": fixture}
        for metric in ("shots", "box_shots", "big_chances", "box_touches"):
            row[f"home_{metric}"] = 100.0
            row[f"away_{metric}"] = 1.0
        event_rows.append(row)
    factors = build_event_factors(matches, pd.DataFrame(event_rows))
    gw1 = factors[factors["gw"] == 1]
    gw2 = factors[factors["gw"] == 2]
    assert np.allclose(gw1["factor_home_shots"], 1.0)
    assert float(gw2.iloc[0]["factor_home_shots"]) > 1.0


def test_weekly_bootstrap_is_paired_and_deterministic():
    rows = [{"baseline": 50, "candidate": 51} for _ in range(38)]
    summary = _weekly_bootstrap(rows, "candidate", draws=200, seed=7)
    assert summary["delta"] == 38
    assert summary["wins"] == 38
    assert summary["ci95"] == [38.0, 38.0]
