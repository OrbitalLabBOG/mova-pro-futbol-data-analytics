import pytest
from experiments.data_ground_truth.discovery_2014 import NUMERIC,PROFILE,TEXT,corroborate,number,reconcile


def rows():
    source={k:'0' for k in PROFILE};source.update({k:'0' for k in NUMERIC})
    source.update(id='1',code='101',GW='1',date='16 Aug 15:00',fixture='ARS(H) 1-0',web_name='Name',type_name='Defender',team_name='Club',V='45',now_cost='46',selected_by='4,7')
    reference={k:'0' for k in NUMERIC.values()}
    reference.update({v:source[k] for k,v in TEXT.items()})
    reference.update(id='1.0',gw='1.0',date=source['date'],opp=source['fixture'],gw_val='4.5',final_season_value='4.6',final_season_ownership='4.7',official_player_code='',matchId='1',match_team_code='3')
    return source,reference


def test_decimal_units_and_source_code_candidate_are_explicit():
    s,r=rows();identities,diff,report=reconcile([s],[r])
    assert report['cell_disagreements']==0 and not diff
    assert identities[0]['status']=='new_source_code_candidate'
    assert not identities[0]['eligible_training'] and identities[0]['available_at'] is None
    with pytest.raises(ValueError):number('nan')


def test_existing_code_conflict_and_cell_difference_are_preserved():
    s,r=rows();r.update(official_player_code='102',gw_pts='1')
    identities,diff,report=reconcile([s],[r])
    assert identities[0]['status']=='conflicts_existing_code'
    assert len(diff)==1 and diff[0]['field']=='P'
    assert report['cell_disagreements']==1


def test_duplicate_source_keys_and_codes_rejected():
    s,r=rows()
    with pytest.raises(ValueError,match='duplicate'):reconcile([s,s],[r])
    with pytest.raises(ValueError,match='multiple'):reconcile([s,dict(s,id='2')],[r])
    with pytest.raises(ValueError,match='profile'):reconcile([s,dict(s,GW='2',code='103')],[r])


def test_missing_minutes_do_not_become_played_witness_and_club_conflicts_block():
    s,r=rows();r['mins']='90';identities,_,_=reconcile([s],[r])
    ref=[r,dict(r,matchId='2')]
    obs=[dict(official_player_code='101',minutesPlayed='90',matchId_events='1',team_id='3'),
         dict(official_player_code='101',minutesPlayed='',matchId_events='2',team_id='3')]
    result=corroborate(identities,ref,obs)
    assert result['observation_rows_without_minutes']==1
    assert not identities[0]['two_played_fixture_corroboration']
    obs[1]['minutesPlayed']='90';corroborate(identities,ref,obs)
    assert identities[0]['two_played_fixture_corroboration']
    obs[1]['team_id']='4';corroborate(identities,ref,obs)
    assert not identities[0]['two_played_fixture_corroboration']


def test_current_gt_prevents_counting_already_resolved_baseline_identity_as_new():
    from experiments.data_ground_truth.discovery_2014 import GT_FIELDS,compare_gt
    s,r=rows();identities,_,_=reconcile([s],[r])
    identities[0]['two_played_fixture_corroboration']=True
    gt={v:s[k] for k,v in GT_FIELDS.items()}
    gt.update(element='1',fixture='1',official_player_code='101')
    report,diff=compare_gt(identities,[s],[r],[gt])
    assert identities[0]['status']=='new_source_code_candidate'
    assert identities[0]['gt_v5_status']=='agrees_existing_code'
    assert report['new_candidate_rows']==0 and not diff
    gt['official_player_code']=''
    report,_=compare_gt(identities,[s],[r],[gt])
    assert report['new_candidate_rows']==1 and report['new_candidate_played_rows']==0
