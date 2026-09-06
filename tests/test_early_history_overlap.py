import pandas as pd
import pytest
from experiments.data_ground_truth.early_history_overlap import compare


def inputs():
    tables={
        'fixture':pd.DataFrame([dict(_id=10,season=14,datetime=1376751600,team_home_id=1,team_away_id=2)]),
        'player_match':pd.DataFrame([dict(season=14,player_player_id=100,fixture_id=10,gameweek=1,pl_team_id=1,opp_team_id=2,minutes=90,total=None)]),
        'player_season':pd.DataFrame([dict(season=14,player_id=100,fpl_id=7)])}
    teams=pd.DataFrame([dict(_id=1,name='Arsenal'),dict(_id=2,name='Villa')])
    players=pd.DataFrame([dict(_id=100,name='Keeper')])
    reference=pd.DataFrame([dict(home_team='Arsenal',home_team_id=3,away_team_id=7,matchId=99,kickoff='2013-08-17 15:00:00'),dict(home_team='Villa',home_team_id=7,away_team_id=3,matchId=98,kickoff='2014-01-01 15:00:00')])
    tables['fixture']=pd.concat([tables['fixture'],pd.DataFrame([dict(_id=11,season=14,datetime=1388588400,team_home_id=2,team_away_id=1)])],ignore_index=True)
    labels=pd.DataFrame([dict(id=7,matchId=99,gw=1,mins=90,gw_pts=6,match_team_code=3,opponent_code=7,official_player_code=123),dict(id=8,matchId=99,gw=1,mins=0,gw_pts=0,match_team_code=3,opponent_code=7,official_player_code=124)])
    metadata=pd.DataFrame([dict(id=7,name='Keeper'),dict(id=8,name='Reserve')])
    return tables,teams,players,reference,labels,metadata


def test_missing_labels_remain_raw_and_complementary_zeros_are_counted():
    args=inputs();frame,report=compare(*args)
    assert report['candidate_missing_points']==1 and report['json_only_explicit_zero_minutes']==1
    row=frame.loc[frame.fpl_id.eq(7)].iloc[0]
    assert pd.isna(row.total) and row.gw_pts==6 and row.candidate_missing_points
    assert not frame.eligible_training.any()


def test_disagreement_prevents_recovery_without_silently_dropping_observations():
    args=inputs();args[0]['player_match']['minutes']=89
    _,r=compare(*args)
    assert r['minutes_conflicts']==1 and r['candidate_missing_points']==0
    args=inputs();args[2]['name']='Another Keeper'
    _,r=compare(*args)
    assert r['name_disagreements']==1 and r['candidate_missing_points']==0
    args=inputs();args[0]['player_season']['player_id']=999
    with pytest.raises(ValueError,match='missing season player identity'):compare(*args)


def test_fixture_disagreement_and_duplicate_rows_fail_closed():
    args=inputs();args[3].loc[0,'kickoff']='2013-08-18 15:00:00'
    with pytest.raises(ValueError,match='fixture date conflict'):compare(*args)
    args=list(inputs());args[4]=pd.concat([args[4],args[4].iloc[:1]],ignore_index=True)
    with pytest.raises(pd.errors.MergeError):compare(*args)
