import pytest
from experiments.data_ground_truth.gaffer_source_audit import compare_profile
from experiments.data_ground_truth.raw import select


def sample():
    return dict(id=1,code=10,minutes=90,total_points=2,fixture_history={'all':[[1,90,2]]},season_history=[['2014/15',30,1]],status='a')


def test_appended_annual_summary_is_distinct_from_match_history():
    old=sample();new=old|dict(season_history=old['season_history']+[['2015_16',90,2]],status='i')
    r=compare_profile(old,new)
    assert r['fixture_history_equal'] and r['prior_annual_history_preserved']
    assert r['appended_minutes_match_snapshot'] and r['appended_points_match_snapshot']
    assert r['changed_fields']==['season_history','status'] and not r['eligible_training']
    new['fixture_history']={'all':[[1,90,3]]}
    assert not compare_profile(old,new)['fixture_history_equal']


def test_identity_mismatch_and_changed_annual_prefix_are_not_silently_accepted():
    old=sample()
    with pytest.raises(ValueError,match='identity mismatch'):compare_profile(old,old|dict(code=11))
    r=compare_profile(old,old|dict(season_history=[['2014/15',31,1],['2015_16',90,2]]))
    assert not r['prior_annual_history_preserved'] and r['appended_season'] is None
    assert select('barryedmund/gaffer','public/player_data/2015_16_10.json')
    assert not select('barryedmund/gaffer','config/database.yml')
    assert not select('barryedmund/gaffer','public/player_data/2014_15_10.json')
