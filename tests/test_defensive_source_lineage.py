from experiments.data_ground_truth.defensive_source_lineage import observed, relationship


def test_absent_row_field_empty_and_zero_remain_distinct():
    assert observed(None,'blocks')['status']=='absent_row'
    assert observed({},'blocks')['status']=='absent'
    assert observed({'blocks':''},'blocks')['status']=='empty'
    assert observed({'blocks':'0'},'blocks')==dict(status='valid',value=0)


def test_prior_value_never_repairs_current_unknown():
    prior=observed({'blocks':'2'},'blocks')
    assert relationship(prior,None)=='valid_to_unknown'
    assert relationship(prior,2)=='equal'
    assert relationship(prior,1)=='different'
    assert relationship(observed(None,'blocks'),0)=='absent_row_to_observed'
