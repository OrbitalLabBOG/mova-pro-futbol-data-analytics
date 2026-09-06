import pandas as pd
import pytest

from experiments.data_ground_truth.cumulative_period import references
from tests.test_gw2_period import row


def test_postponed_fixture_is_excluded_by_time_despite_earlier_gw():
    frame = pd.DataFrame([dict(row(1, 1, 10, 90), event_time_utc='2025-08-01T12:00:00Z'),
                          dict(row(2, 1, 10, 80), event_time_utc='2025-09-01T12:00:00Z')])
    nominal, temporal, diagnostics = references(frame, 3, '2025-08-20T12:00:00Z')
    assert nominal[10]['values']['minutes'] == 170
    assert temporal[10]['values']['minutes'] == 90
    assert diagnostics['differing_row_membership'] == 1


def test_unknown_time_invalidates_partial_sum_and_naive_cutoff_rejected():
    frame = pd.DataFrame([dict(row(1, 1, 10, 90), event_time_utc=None)])
    _, temporal, diagnostics = references(frame, 2, '2025-08-20T12:00:00Z')
    assert temporal[10]['status'] == 'unknown_event_time'
    assert diagnostics['missing_event_times'] == 1
    with pytest.raises(ValueError, match='timezone'):
        references(frame, 2, '2025-08-20T12:00:00')


def test_exact_deadline_kickoff_is_excluded_and_earlier_future_gw_included():
    frame = pd.DataFrame([dict(row(8, 1, 10, 90), event_time_utc='2025-08-20T11:00:00Z'),
                          dict(row(1, 1, 10, 80), event_time_utc='2025-08-20T12:00:00Z')])
    nominal, temporal, diagnostics = references(frame, 3, '2025-08-20T12:00:00Z')
    assert nominal[10]['values']['minutes'] == 80
    assert temporal[10]['values']['minutes'] == 90
    assert diagnostics['kickoffs_within_four_hours'] == 1
