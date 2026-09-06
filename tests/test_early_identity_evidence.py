import pandas as pd
import pytest
from experiments.data_ground_truth.early_identity_evidence import reference_check,scoped_links


def test_name_code_and_annual_evidence_must_all_agree():
    later=dict(first_name='Isaiah',second_name='Brown',code=112516,season_history=[['2014/15',12,1]])
    profiles=pd.DataFrame([dict(code=112516,first_name='Isaiah',second_name='Brown')])
    gt=pd.DataFrame([dict(element=93,official_player_code=112516,minutes=12,total_points=1)])
    assert reference_check(later,profiles,gt)['canonical_code']==112516
    gt['total_points']=2
    with pytest.raises(ValueError,match='annual totals mismatch'):reference_check(later,profiles,gt)
    profiles['first_name']='Wes'
    with pytest.raises(ValueError,match='profile identity ambiguous'):reference_check(later,profiles,gt)


def test_scoped_mapping_preserves_observed_code_and_rejects_collisions():
    p=dict(id=93,code=81132,first_name='Isaiah',second_name='Brown')
    r=dict(sha256='a'*64,repository='owner/repo',revision='b'*40,path='data.json')
    x=scoped_links([p],r,112516)[0]
    assert x['observed_code']==81132 and x['candidate_canonical_code']==112516
    assert not x['global_alias_admitted'] and not x['eligible_training']
    with pytest.raises(ValueError,match='different name'):scoped_links([p|dict(first_name='Wes')],r,112516)
    with pytest.raises(ValueError,match='duplicate source player IDs'):scoped_links([p,p],r,112516)
    with pytest.raises(ValueError,match='duplicate observed code'):scoped_links([p,p|dict(id=94)],r,112516)
