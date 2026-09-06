import pandas as pd
from experiments.data_ground_truth.profile_history_reconciliation import compare,resolve


def player(history=True):
    row=['16 Aug 15:00',1,'CRY(H) 2-1',90]+[0]*15+[2]
    return dict(id=1,code=123,web_name='Player',total_points=2,fixture_history={'all':[row] if history else []})


def test_season_requires_unique_calendar_and_real_profile_total():
    f=pd.DataFrame([dict(matchId=8,kickoff='2014-08-16 15:00',home_team_id=3,away_team_id=31)])
    labels,_,report=resolve([player()],{2014:f})
    assert report['status']=='reconciled' and labels.season.iloc[0]=='2014-15'
    other=f.copy();other.kickoff='2015-08-16 15:00'
    assert resolve([player()],{2014:f,2015:other})[2]['status']=='ambiguous_season'
    assert resolve([dict(player(),total_points=3)],{2014:f})[2]['status']=='unreconciled'
    assert resolve([player(False)],{2014:f})[2]['status']=='no_history'


def test_provisional_disagreement_is_retained_not_repaired():
    labels=pd.DataFrame([dict(id=1,matchId=8,gw=1,mins=45,gw_pts=1,code=123)])
    gt=pd.DataFrame([dict(element=1,fixture=8,gw=1,minutes=90,total_points=2,official_player_code=123)])
    report,bad=compare(labels,gt)
    assert report['minutes_conflict']==report['points_conflict']==1
    assert report['gameweek_conflict']==report['code_conflict']==0
    assert bad.iloc[0].mins==45 and bad.iloc[0].minutes==90
    assert labels.iloc[0].mins==45 and gt.iloc[0].minutes==90
