import pandas as pd
from experiments.data_ground_truth.annual_residual_evidence import residual,audit


def rows():
    return pd.DataFrame(dict(minutes=[90,20],total=[4,None],candidate_missing_points=[False,False],gw_pts=[4,None]))


def test_conditional_residual_preserves_unknown_source_and_is_not_observed():
    g=rows();r=residual(g,['2013/14',110,4])
    assert r['inferred_points']==0 and r['status']=='conditional_annual_residual'
    assert pd.isna(g.iloc[1].total) and not r['observed_label'] and not r['eligible_training']
    assert residual(g,['2013/14',110,6])['inferred_points']==2


def test_ambiguity_and_missing_minutes_do_not_impute_zero():
    g=rows();g['total']=None
    assert residual(g,['2013/14',110,0])['status']=='not_one_unknown_point_row'
    g=rows();g.loc[0,'minutes']=None
    assert residual(g,['2013/14',20,4])['status']=='missing_minutes'
    assert residual(rows(),['2013/14',111,4])['status']=='annual_minutes_disagree'
    assert residual(rows(),None)['inferred_points'] is None


def test_annual_reference_with_different_name_is_not_used():
    g=rows();g['source_presence']='left_only';g['fpl_id']=7;g['differential_name']='Brown';g['matchId']=[1,2];g['gameweek']=[1,34]
    ep=[dict(id=7,code=100,first_name='Wes',second_name='Brown')]
    lp=[dict(id=8,code=100,first_name='Isaiah',second_name='Brown',season_history=[['2013/14',110,4]])]
    cases=audit(g,ep,lp)
    assert len(cases)==1 and not cases[0]['identity_corroborated']
    assert cases[0]['status']=='missing_annual_reference' and cases[0]['inferred_points'] is None
