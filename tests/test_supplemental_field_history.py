from experiments.data_ground_truth.supplemental_field_history import profile


def test_absent_zero_and_populated_states_are_distinct():
    assert profile([{},{}],'expected_goals')['regime']=='absent'
    assert profile([{'expected_goals':'0.00000'}],'expected_goals')['regime']=='all_zero'
    assert profile([{'expected_goals':'1.23000'}],'expected_goals')['regime']=='positive_hundredth_compatible'
    assert profile([{'expected_goals':'1.23400'}],'expected_goals')['regime']=='positive_subcent_precision'


def test_partial_and_invalid_population_is_not_reported_as_complete():
    result=profile([{'starts':1},{'starts':None},{}],'starts')
    assert result['regime']=='partial_or_invalid'
    assert result['statuses']==dict(valid=1,null=1,absent=1)
    assert profile([{'expected_goals':'NaN'}],'expected_goals')['regime']=='partial_or_invalid'
