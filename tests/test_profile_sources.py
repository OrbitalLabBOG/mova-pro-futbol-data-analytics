import pandas as pd
import pytest
from experiments.data_ground_truth.profile_sources import compare


def frames():
    return (pd.DataFrame([dict(id=1,matchId=8,mins=0,gw_pts=0,gw=38)]),
            pd.DataFrame([dict(id=1,code=123)]),
            pd.DataFrame([dict(element=1,fixture=8,minutes=0,total_points=0,gw=38,official_player_code=None)]))


def test_candidate_requires_matching_observations():
    a,b,c=frames();c.loc[0,'minutes']=90
    with pytest.raises(ValueError,match='label disagreement'):compare(a,b,c)
    c.loc[0,'minutes']=0
    candidates,report=compare(a,b,c)
    assert candidates.to_dict('records')==[dict(element=1,candidate_official_player_code=123)]
    assert report['candidate_identity_rows']==1
    assert c.official_player_code.isna().all()


def test_conflicting_existing_identity_is_rejected():
    a,b,c=frames();c['official_player_code']=456
    with pytest.raises(ValueError,match='identity conflict'):compare(a,b,c)
    b=pd.concat([b,pd.DataFrame([dict(id=2,code=123)])],ignore_index=True)
    with pytest.raises(ValueError,match='ambiguous'):compare(a,b,c)
