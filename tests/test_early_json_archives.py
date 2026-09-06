import pandas as pd
import pytest
from experiments.data_ground_truth.early_json_archives import normalize
from experiments.data_ground_truth.raw import select


def source():
    row=['17 Aug 15:00',1,'AVL(H) 1-3',0]+[0]*14+[45,0]
    player=dict(id=1,code=1000,team_code=1000,team_name='Arsenal',web_name='Keeper',total_points=0,
                season_history=[['2012/13',0]],fixture_history={'all':[row]})
    fixtures=pd.DataFrame([dict(matchId=1,kickoff='2013-08-17 15:00:00',home_team_id=3,away_team_id=7)])
    return [player],fixtures


def test_bad_team_code_is_preserved_and_not_used_for_fixture_link():
    players,fixtures=source();labels,metadata,report=normalize(players,fixtures,2013)
    assert labels.iloc[0].match_team_code==3
    assert metadata.iloc[0].declared_team_code==1000
    assert report['declared_team_code_not_in_fixture_clubs']==1
    assert report['explicit_zero_minute_rows']==1
    assert not labels.eligible_training.any()
    players[0]['total_points']=1
    with pytest.raises(ValueError,match='total reconciliation'):
        normalize(players,fixtures,2013)


def test_source_selection_and_year_or_schema_mismatch_fail_closed():
    assert select('keithxm23/fplPlayer','data.json')
    assert not select('keithxm23/fplPlayer','predict.py')
    assert not select('keithxm23/fplassistant','config/database.yml')
    players,fixtures=source()
    with pytest.raises(ValueError,match='declared season'):
        normalize(players,fixtures,2014)
    players[0]['fixture_history']['all'][0].append(1)
    with pytest.raises(ValueError,match='unknown snapshot'):
        normalize(players,fixtures,2013)


def test_players_without_history_are_retained_without_fabricated_zero_rows():
    players,fixtures=source()
    players.append(players[0]|dict(id=2,code=1001,fixture_history={'all':[]}))
    labels,metadata,report=normalize(players,fixtures,2013)
    assert len(metadata)==2 and len(labels)==1
    assert report['snapshot_players_without_history']==1
    assert report['snapshot_total_players_checked']==1
