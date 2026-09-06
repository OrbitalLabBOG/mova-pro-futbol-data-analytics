import pandas as pd
import pytest

from experiments.data_ground_truth.partial_history_integrity import audit


def tables():
    return dict(
        player_match=pd.DataFrame([dict(season=12, player_player_id=7, fixture_id=1,
            gameweek=1, pl_team_id=2, opp_team_id=1, is_home=None, minutes=90, total=0)]),
        fixture=pd.DataFrame([dict(season=12, _id=1, gameweek=1, team_home_id=1, team_away_id=2)]),
        player_season=pd.DataFrame([dict(season=12, player_id=7, fpl_id=99)]),
    )


def test_null_venue_is_derived_without_imputing_raw_or_points():
    source = tables()
    frame, _ = audit(source)
    assert pd.isna(frame.iloc[0].is_home)
    assert frame.iloc[0].derived_is_home == 0
    assert frame.iloc[0].structurally_valid_observed_label
    assert not frame.eligible_training.any()
    source['player_match'].loc[0, 'total'] = None
    frame, _ = audit(source)
    assert not frame.iloc[0].structurally_valid_observed_label
    assert frame.iloc[0].quality_issues == 'missing_points'
    assert pd.isna(frame.iloc[0].total)


def test_conflicting_clubs_venue_and_duplicate_keys_are_not_accepted():
    source = tables()
    source['player_match'].loc[0, 'is_home'] = 1
    frame, _ = audit(source)
    assert frame.iloc[0].quality_issues == 'venue_conflict'
    source['player_match'].loc[0, 'pl_team_id'] = 3
    frame, _ = audit(source)
    assert 'invalid_club_pair' in frame.iloc[0].quality_issues
    assert pd.isna(frame.iloc[0].derived_is_home)
    source = tables()
    source['player_match'] = pd.concat([source['player_match']] * 2, ignore_index=True)
    frame, _ = audit(source)
    assert not frame.structurally_valid_observed_label.any()
    source = tables()
    source['fixture'] = pd.concat([source['fixture']] * 2, ignore_index=True)
    with pytest.raises(pd.errors.MergeError):
        audit(source)


def test_cross_season_fixture_and_fractional_labels_are_rejected():
    source = tables()
    source['fixture'].loc[0, 'season'] = 13
    frame, _ = audit(source)
    assert 'missing_fixture' in frame.iloc[0].quality_issues
    source = tables()
    source['player_match']['minutes'] = 90.5
    source['player_match']['total'] = -1.5
    frame, _ = audit(source)
    assert 'invalid_minutes' in frame.iloc[0].quality_issues
    assert 'invalid_points' in frame.iloc[0].quality_issues
    source['player_match']['minutes'] = 90
    source['player_match']['total'] = -1
    frame, _ = audit(source)
    assert frame.iloc[0].structurally_valid_observed_label
