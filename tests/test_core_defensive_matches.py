import pandas as pd
import pytest

from experiments.data_ground_truth.core_defensive_matches import fixture_links


def inputs():
    teams = pd.DataFrame({'id': [1, 2], 'code': [10, 20]})
    fixtures = pd.DataFrame({'id': [99, 100], 'team_h': [1, 2], 'team_a': [2, 1],
                             'kickoff_time': ['2024-08-17T14:00:00Z', '2025-02-01T15:00:00Z']})
    matches = pd.DataFrame({'match_id': ['a', 'b'], 'home_team': [10, 20], 'away_team': [20, 10],
                            'kickoff_time': ['2024-08-17 14:00:00', '2025-02-01 15:00']})
    return matches, fixtures, teams


def test_directed_clubs_and_date_are_required_not_just_club_pair():
    matches, fixtures, teams = inputs()
    assert fixture_links(matches, fixtures, teams).id.tolist() == [99, 100]
    matches.loc[0, 'kickoff_time'] = '2024-08-18 14:00:00'
    assert pd.isna(fixture_links(matches, fixtures, teams).id.iloc[0])
    matches.loc[0, 'kickoff_time'] = '2024-08-17 14:00:00'
    matches.loc[0, ['home_team', 'away_team']] = [20, 10]
    assert pd.isna(fixture_links(matches, fixtures, teams).id.iloc[0])


def test_ambiguous_fixture_mapping_rejected():
    matches, fixtures, teams = inputs()
    with pytest.raises(ValueError, match='ambiguous directed'):
        fixture_links(matches, pd.concat([fixtures, fixtures.iloc[:1]]), teams)
    teams.loc[1, 'code'] = 10
    with pytest.raises(ValueError, match='ambiguous official team'):
        fixture_links(matches, fixtures, teams)
