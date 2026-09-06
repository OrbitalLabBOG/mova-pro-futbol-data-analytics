import pandas as pd
import pytest
from experiments.data_ground_truth.snapshots import unpack
from experiments.data_ground_truth.unscored_history_rows import map_rows


def inputs(opponent='CRY(H) ',minutes=0,points=0):
    row=['16 Aug 15:00',1,opponent,minutes]+[0]*15+[points]
    weekly,meta=unpack([dict(id=1,code=123,web_name='Player',total_points=points,fixture_history={'all':[row]})])
    fixtures=pd.DataFrame([dict(matchId=8,kickoff='2014-08-16 15:00',home_team_id=3,away_team_id=31)])
    return weekly,meta,fixtures


def test_missing_score_is_not_replaced_with_zero_score():
    w,m,f=inputs();mapped=map_rows(w,m,f,2014)
    assert mapped.matchId.iloc[0]==8
    assert not mapped.source_score_present.iloc[0]
    assert pd.isna(mapped.source_own_score.iloc[0])
    assert mapped.opp.iloc[0]=='CRY(H) '
    assert not mapped.final_observation_proven.iloc[0]


def test_scoreless_live_stats_and_totals_are_preserved():
    w,m,f=inputs(minutes=45,points=1);mapped=map_rows(w,m,f,2014)
    assert mapped.mins.iloc[0]==45 and mapped.gw_pts.iloc[0]==1
    assert not mapped.source_score_present.iloc[0]
    m.pts=3
    with pytest.raises(ValueError,match='total mismatch'):map_rows(w,m,f,2014)
    w,m,f=inputs(opponent='CRY(H) 0-0')
    assert map_rows(w,m,f,2014).source_score_present.iloc[0]
    assert not map_rows(w,m,f,2014).final_observation_proven.iloc[0]
