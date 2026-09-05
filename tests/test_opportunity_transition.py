import copy

import numpy as np
import pytest

from experiments.season_value.transition import CHIPS, OpportunityTransition, evaluate_transition


def rows(season):
    return [{'season': season, 'gw': i, 'values': {c: float((i // 5) % 3 + j + 1)
             for j, c in enumerate(CHIPS)}, 'structure': {c: 1. for c in CHIPS}}
            for i in range(2, 39)]


def test_future_training_and_duplicate_rows_fail():
    with pytest.raises(ValueError, match='prior'):
        OpportunityTransition().fit(rows('2024-25'), target_season='2024-25')
    with pytest.raises(ValueError, match='duplicate'):
        OpportunityTransition().fit(rows('2023-24') * 2, target_season='2024-25')


def test_no_transition_across_season_or_missing_gameweek():
    data = rows('2022-23') + rows('2023-24')
    data = [r for r in data if not (r['season'] == '2023-24' and r['gw'] == 10)]
    m = OpportunityTransition().fit(data, target_season='2024-25')
    assert m.metadata['transitions'] == 70
    assert np.allclose(m.transition.sum(axis=1), 1)
    assert np.isclose(m.weights(rows('2024-25')[0], conditioned=True).sum(), 1)


def test_forecast_does_not_read_future_outcome():
    m = OpportunityTransition().fit(rows('2023-24'), target_season='2024-25')
    a, b = rows('2024-25')[:2]
    before = m.weights(a, conditioned=True).copy()
    other = copy.deepcopy(b)
    other['values']['wildcard'] = 999.
    m.score(a, other, conditioned=True)
    assert np.array_equal(before, m.weights(a, conditioned=True))
    with pytest.raises(ValueError, match='consecutive'):
        m.score(a, {**b, 'gw': 15}, conditioned=True)


def test_screen_is_deterministic_and_never_promotes():
    a = evaluate_transition(rows('2023-24'), rows('2024-25'))
    b = evaluate_transition(rows('2023-24'), rows('2024-25'))
    assert a == b
    assert a['pairs'] == 36
    assert a['promotion_authorized'] is False
    assert a['policy_points_evaluated'] is False


def test_markov_bellman_two_week_value_matches_enumeration():
    from experiments.season_value.transition_planner import MarkovSeasonValue
    from mova_fpl.engine.state import State
    from mova_fpl.rules.chips import ChipCatalogue, ChipWindow
    m = MarkovSeasonValue().fit(rows('2023-24'), target_season='2024-25')
    cat = ChipCatalogue(('bench_boost',), (ChipWindow('test', 1, 2),))
    s = State(season='2024-25', gw=1, candidates=(), chips=cat)
    chip, evidence = m.choose(s, {'bench_boost': 2.})
    regime = evidence['regime']
    raw = m.markov.support * m.markov.scale
    future = sum(m.markov.transition[regime, j] * raw[m.markov.labels == j, 0].mean()
                 for j in range(3))
    assert evidence['hold_value'] == pytest.approx(future)
    assert evidence['q_values']['bench_boost'] == 2.
    assert chip == ('bench_boost' if 2 > future else None)


def test_markov_expiry_and_spent_inventory():
    from dataclasses import replace
    from experiments.season_value.transition_planner import MarkovSeasonValue
    from mova_fpl.engine.state import State
    from mova_fpl.rules.chips import ChipCatalogue, ChipWindow, ChipUse
    m = MarkovSeasonValue().fit(rows('2023-24'), target_season='2024-25')
    s = State(season='2024-25', gw=38, candidates=(),
              chips=ChipCatalogue(CHIPS, (ChipWindow('season', 1, 38),)))
    chip, e = m.choose(s, {'bench_boost': 4., 'triple_captain': 6.})
    assert chip == 'triple_captain' and e['hold_value'] == 0
    chip, e = m.choose(replace(s, chips_used=(ChipUse(2, 'triple_captain'),)),
                       {'bench_boost': 4., 'triple_captain': 999.})
    assert chip == 'bench_boost'
    assert 'triple_captain' not in e['q_values']


def test_paired_projection_rejects_predictor_state_contamination(monkeypatch):
    import pandas as pd
    from experiments.long_horizon.projection import FixtureProjector
    from experiments.season_value.transition_replay import PairedProjector
    from mova_fpl.engine.simulator import ProjectionBundle
    current = [5.]
    monkeypatch.setattr(FixtureProjector, '__call__', lambda self, **kw:
                        ProjectionBundle(pd.Series(current), {2: {1: current[0]}}))
    control = PairedProjector()
    control(gw=2)
    candidate = PairedProjector(control.hashes)
    candidate(gw=2)
    current[0] = 6.
    with pytest.raises(ValueError, match='paired forecast mismatch'):
        candidate(gw=2)
