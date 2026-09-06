import pytest

from experiments.data_ground_truth.statsbomb_open import fixture_coverage, match_ids


def fixture(home, away):
    return {'home_team': {'home_team_id': home}, 'away_team': {'away_team_id': away}}


def test_380_matches_not_sufficient_if_pair_is_duplicated():
    matches = [fixture(a, b) for a in range(20) for b in range(20) if a != b]
    assert fixture_coverage(matches)['complete_20_team_double_round_robin'] is True
    matches[-1] = matches[0]
    coverage = fixture_coverage(matches)
    assert coverage['complete_20_team_double_round_robin'] is False
    assert coverage['missing_directed_pairs'] == 1
    assert coverage['duplicate_pair_excess'] == 1


def test_single_club_season_is_not_a_full_league():
    matches = [fixture(a, b) for a in range(20) for b in range(20) if a != b and (a == 0 or b == 0)]
    assert fixture_coverage(matches)['matches'] == 38
    assert fixture_coverage(matches)['complete_20_team_double_round_robin'] is False


def test_duplicate_or_boolean_match_id_is_rejected():
    with pytest.raises(ValueError): match_ids([{'match_id': 1}, {'match_id': 1}])
    with pytest.raises(ValueError): match_ids([{'match_id': True}])
    assert match_ids([{'match_id': 1}, {'match_id': 2}]) == [1, 2]
