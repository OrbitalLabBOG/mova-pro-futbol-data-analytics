"""Boundary and historical witness checks for the research arithmetic audit."""
import pytest
from experiments.data_ground_truth.legacy_scoring_audit import COMPONENTS, integer, score


def row(**values):
    return dict.fromkeys(COMPONENTS, '0') | values


def test_archived_silva_toure_witnesses_and_partial_substitution():
    silva = row(minutes='90', assists='1', clean_sheets='1')
    toure = row(minutes='79', goals_scored='2', clean_sheets='1', bonus='3')
    assert score(silva, 3) == 6
    assert score(toure, 3) == 16
    assert score(silva | {'goals_scored': '1'}, 3) == 11
    assert score(toure | {'goals_scored': '1'}, 3) == 11


def test_thresholds_position_and_negative_points():
    assert score(row(minutes='59'), 2) == 1
    assert score(row(minutes='60'), 2) == 2
    assert score(row(minutes='90', saves='8', goals_conceded='3', penalties_saved='1'), 1) == 8
    assert score(row(minutes='1', own_goals='1', red_cards='1'), 2) == -4
    assert [score(row(goals_scored='1'), p) for p in (1, 2, 3, 4)] == [6, 6, 5, 4]
    assert integer('-4', signed=True) == -4


def test_missing_not_zero_and_invalid_values_rejected():
    assert score(row(assists=''), 3) is None
    assert integer(None) is None
    for value in ('NaN', 'Infinity', '-1', '0.5', 'oops'):
        with pytest.raises(ValueError):
            integer(value)
    with pytest.raises(ValueError):
        score(row(), 5)
