from copy import deepcopy

import pytest

from experiments.data_ground_truth.published_manager_reference import COHORTS, reconcile


def reference():
    weekly = [dict(published_cohort=c, gw=g, mean_points='1.00') for c in COHORTS for g in range(1, 39)]
    summary = [dict(published_cohort='Everyone', n='40', Mean='38.00')]
    summary += [dict(published_cohort=c, n='10', Mean='38.00') for c in COHORTS]
    return weekly, summary


def test_rounding_compatibility_does_not_accept_material_score_difference():
    weekly, summary = reference()
    summary[1]['Mean'] = '38.02'
    assert reconcile(weekly, summary)[0]['difference'] == '-0.02'
    summary[1]['Mean'] = '40.00'
    with pytest.raises(ValueError, match='beyond rounding'):
        reconcile(weekly, summary)


def test_missing_gameweek_and_inconsistent_cohort_counts_are_rejected():
    weekly, summary = reference()
    changed = deepcopy(weekly); changed[0]['gw'] = 2
    with pytest.raises(ValueError, match='incomplete'):
        reconcile(changed, summary)
    summary[0]['n'] = '41'
    with pytest.raises(ValueError, match='sizes'):
        reconcile(weekly, summary)
