import pandas as pd
import pytest
from experiments.data_ground_truth.early_successor_archive import inspect_snapshot,validate_inventory
from experiments.data_ground_truth.raw import select


def test_inventory_requires_exact_revisions_and_source():
    history=[dict(sha='a'*40,commit={'committer':{'date':'2014-08-15T00:00:00Z'}})]
    records=[dict(repository='keithxm23/fplassistantv2',path='data.json',revision='a'*40)]
    assert len(validate_inventory(records,history))==1
    with pytest.raises(ValueError,match='incomplete or duplicate'):validate_inventory(records*2,history)
    with pytest.raises(ValueError,match='unexpected source'):validate_inventory([records[0]|dict(path='config/database.yml')],history)
    assert select('keithxm23/fplassistantv2','data.json')
    assert not select('keithxm23/fplassistantv2','config/database.yml')


def test_unscored_rows_and_empty_histories_are_retained_without_reconciliation():
    row=['16 Aug 15:00',1,'AVL(H) ',0]+[0]*14+[45,0]
    p=dict(id=1,code=1000,team_code=3,team_name='Arsenal',web_name='Keeper',total_points=0,
           season_history=[['2013/14',0]],fixture_history={'all':[row]})
    f=pd.DataFrame([dict(matchId=1,kickoff='2014-08-16 15:00:00',home_team_id=3,away_team_id=7)])
    labels,_,r=inspect_snapshot([p],f)
    assert len(labels)==1 and r['normalization_status']=='unreconciled'
    assert r['season_points_disagreements'] is None
    p['fixture_history']={'all':[]}
    labels,m,r=inspect_snapshot([p],f)
    assert len(labels)==0 and len(m)==1 and r['normalization_status']=='no_history'
