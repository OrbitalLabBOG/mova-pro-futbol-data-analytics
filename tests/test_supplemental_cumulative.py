from decimal import Decimal

from experiments.data_ground_truth.supplemental_cumulative import compare


def test_exact_decimal_and_rounding_bound_are_separate_verdicts():
    args=dict(total=Decimal('0.30'),count=2,unknown=False,two_decimal=True,field='expected_goals')
    assert compare(dict(status='valid',value='0.30'),**args)['status']=='equal'
    assert compare(dict(status='valid',value='0.31'),**args)['status']=='within_rounding_bound'
    assert compare(dict(status='valid',value='0.32'),**args)['status']=='outside_rounding_bound'
    assert compare(dict(status='valid',value='0.301'),**args)['status']=='different'


def test_unknowns_and_integer_components_cannot_pass_by_rounding():
    args=dict(total=Decimal('1'),count=50,unknown=False,two_decimal=True,field='starts')
    assert compare(dict(status='valid',value=2),**args)['status']=='different'
    assert compare(dict(status='valid',value=1),**dict(args,unknown=True))['status']=='unknown_reference_component'
    assert compare(dict(status='valid',value=0),**dict(args,count=0))['status']=='no_reference_rows'
    assert compare(dict(status='absent',value=None),**args)['status']=='snapshot_absent'
