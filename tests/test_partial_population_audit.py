import pandas as pd
import pytest
from experiments.data_ground_truth.partial_population_audit import summarize,audit


def test_missing_points_do_not_erase_minutes_and_unknown_minutes_are_not_zero():
    f=pd.DataFrame(dict(minutes=[90,0,None,20],total_points=[2,0,None,None]))
    r=summarize(f)
    assert r['known_minute_rows']==3 and r['positive_minute_rows']==2
    assert r['explicit_zero_minute_rows']==1 and r['unknown_minute_rows']==1
    assert r['observed_point_and_minute_rows']==2 and r['known_minutes_missing_points']==1
    assert r['registered_player_denominator'] is None and not r['participation_training_admitted']
    r=summarize(f.iloc[2:3])
    assert r['positive_share_among_known_minutes'] is None and r['sampling_status']=='no_known_minutes'


def test_positive_only_window_is_flagged_and_invalid_fixture_assignment_fails():
    f=pd.DataFrame(dict(season=['2013-14']*3,element=[1,2,3],fixture=[10,10,20],gw=[1,1,31],minutes=[90,0,90],total_points=[2,0,2]))
    fixtures,weeks,r=audit(f)
    assert r['positive_only_gameweeks']==[31]
    assert r['fixtures_with_explicit_zero_minutes']==1
    assert r['fixtures_with_only_positive_known_minutes']==1
    assert weeks.iloc[1].positive_share_among_known_minutes==1
    assert not weeks.eligibility_population_proven.any()
    f.loc[1,'gw']=2
    with pytest.raises(ValueError,match='multiple gameweeks'):audit(f)
