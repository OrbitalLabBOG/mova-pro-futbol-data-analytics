import pytest
from experiments.data_ground_truth.statsbomb_fixture_crosswalk import unique_pair_index, score


def test_reversed_fixture_is_not_the_same_match():
    rows=[{'home_team_id':1,'away_team_id':2},{'home_team_id':2,'away_team_id':1}]
    assert len(unique_pair_index(rows))==2
    with pytest.raises(ValueError): unique_pair_index(rows+[rows[0]])


def test_unknown_score_is_not_zero():
    assert score('') is None
    assert score('0.0')==0
    with pytest.raises(ValueError):score('-1')
