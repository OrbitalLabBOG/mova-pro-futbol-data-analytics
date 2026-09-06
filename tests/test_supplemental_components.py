import pytest

from experiments.data_ground_truth.supplemental_components import cells, linkage


def test_csv_absence_null_zero_and_invalid_values_are_distinct():
    result=cells(dict(expected_goals='',expected_assists='0.00',starts='2',tackles='-1'))
    assert result['expected_goals']['status']=='null'
    assert result['expected_assists']==dict(status='valid',value='0.00')
    assert result['recoveries']['status']=='absent'
    assert result['starts']['status']=='invalid_match_starts'
    assert result['tackles']['status']=='negative'


def test_linkage_requires_same_gameweek_and_qualified_matching_time():
    row=dict(round='3',kickoff_time='2025-08-20T12:00:00Z')
    ref=dict(gw='3',event_time_utc='2025-08-20T13:00:00+01:00')
    assert linkage(row,ref)=='linked'
    assert linkage(row,None)=='no_player_reference'
    assert linkage(row,dict(ref,gw='4'))=='gameweek_mismatch'
    assert linkage(row,dict(ref,event_time_utc=''))=='unknown_match_time'
    assert linkage(row,dict(ref,event_time_utc='2025-08-20T14:00:00Z'))=='kickoff_mismatch'
    with pytest.raises(ValueError,match='unqualified'):
        linkage(row,dict(ref,event_time_utc='2025-08-20T12:00:00'))
