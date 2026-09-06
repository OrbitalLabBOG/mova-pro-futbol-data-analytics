import pytest

from experiments.data_ground_truth.selection_flags import observation


@pytest.mark.parametrize('value,kind', [(None, 'null'), (0, 'invalid_type'), ('false', 'invalid_type')])
def test_unknown_flags_never_become_false(value, kind):
    row = observation(dict(status='u', can_select=value))
    assert row['observed_selectability'] is None
    assert row['flags']['can_select']['kind'] == kind
    assert row['status_u_rule_disagrees'] is False
    absent = observation(dict(status='u'))
    assert absent['flags']['can_select']['kind'] == 'absent'
    assert absent['observed_selectability'] is None


def test_injury_and_transaction_flags_are_separate_from_selection():
    injured = observation(dict(status='i', can_select=True))
    assert injured['observed_selectability'] is True
    assert injured['status_a_filter_would_exclude_observed_selectable'] is True
    unavailable = observation(dict(status='u', can_select=False, can_transact=True))
    assert unavailable['transact_true_select_false'] is True
    contradiction = observation(dict(status='u', can_select=True))
    assert contradiction['observed_selectability'] is True
    assert contradiction['status_u_rule_disagrees'] is True
    assert contradiction['training_admitted'] is False
