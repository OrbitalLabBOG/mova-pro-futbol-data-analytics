import pytest

from experiments.data_ground_truth.profile_total_consistency import observe


def test_inconsistent_total_preserved_and_not_finalized():
    row = ['date', 1, 'ARS(H) ', 5]+[0]*15+[1]
    player = dict(id=1, code=42, total_points=0, fixture_history={'all':[row]})
    state = observe({'1':player}, 1, 42)
    assert state['status']=='total_mismatch' and state['history_minus_profile']==1
    assert state['last_history_row']==row and player['total_points']==0
    player['total_points']=1
    state = observe({'1':player}, 1, 42)
    assert state['status']=='consistent' and not state['final_observation_proven']
    assert not state['eligible_training']


def test_identity_and_source_types_are_checked():
    player = dict(id=1, code=42, total_points=0, fixture_history={'all':[]})
    assert observe({'1':player}, 1, 99)['status']=='identity_mismatch'
    assert observe({}, 1, 42)['status']=='profile_absent'
    player['total_points']=1.5
    with pytest.raises(ValueError, match='nonintegral'):
        observe({'1':player}, 1, 42)
