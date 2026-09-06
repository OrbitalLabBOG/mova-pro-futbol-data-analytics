import pytest

from experiments.data_ground_truth.defensive_match_calibration import count, compare_value, stratum


def test_unknown_provider_or_reference_is_not_zero_or_match():
    assert count(float('nan')) is None
    assert compare_value(None, dict(status='valid', value=0))['status']=='provider_unknown'
    assert compare_value(0, None)['status']=='no_FPL_reference'
    assert compare_value(0, dict(status='absent', value=None))['status']=='FPL_absent'


def test_disagreement_keeps_both_values():
    assert compare_value(3, dict(status='valid', value=2)) == dict(status='different', provider_value=3, FPL_value=2, delta=1)
    assert compare_value(0, dict(status='valid', value=0))['status']=='equal'


@pytest.mark.parametrize('value',[True,-1,1.5,float('inf')])
def test_invalid_provider_counts_rejected(value):
    with pytest.raises(ValueError,match='invalid'):
        count(value)


@pytest.mark.parametrize('minutes,position,expected',[(90,1,'played_goalkeepers'),(1,3,'played_outfield'),
    (0,2,'zero_FPL_minutes'),(0,None,'unknown_minutes_or_position')])
def test_strata_do_not_mix_goalkeepers_nonplayers_or_unknown_positions(minutes,position,expected):
    assert stratum(dict(FPL_minutes=minutes,position=position))==expected
