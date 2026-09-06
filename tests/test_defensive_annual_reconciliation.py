import pytest

from experiments.data_ground_truth.defensive_annual_reconciliation import composition, compare_player


def actions():
    return dict(clearances=4, blocks=1, interceptions=2, tackles=3, tackles_won=2, recoveries=5)


def test_position_and_tackle_definition_are_explicit():
    assert composition(actions(), 2) == 10
    assert composition(actions(), 3) == 15
    assert composition(actions(), 4, 'tackles_won') == 14
    assert composition(actions(), 1) is None


def test_missing_reference_and_goalkeeper_are_not_zero():
    annual = dict(status='observed_value', value=0)
    assert compare_player(annual, None, 2)['status'] == 'no_provider_appearance_reference'
    assert compare_player(annual, actions(), 1)['status'] == 'goalkeeper_out_of_scope'
    assert compare_player(annual, actions(), None)['status'] == 'no_position_in_2025_GW1'


def test_sensitivity_agreement_does_not_replace_primary():
    result = compare_player(dict(status='observed_value', value=14), actions(), 3)
    assert result['primary_delta'] == 1
    assert result['sensitivity_delta'] == 0
    values = actions(); values['tackles'] = None
    assert composition(values, 2) is None
    values['tackles'] = -1
    with pytest.raises(ValueError, match='invalid'):
        composition(values, 2)
