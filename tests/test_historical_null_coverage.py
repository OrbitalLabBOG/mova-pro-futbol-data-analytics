import pandas as pd

from experiments.data_ground_truth.historical_null_coverage import label_coverage


def test_missing_labels_are_distinct_from_zero_and_negative_scores():
    frame = pd.DataFrame({'minutes': [90, 20, None, None, 0, 45],
                          'total': [None, 0, 3, None, 0, -1]})
    original = frame.copy(deep=True)
    result = label_coverage(frame)
    assert result['both_labels'] == 3
    assert result['minutes_only'] == 1
    assert result['points_only'] == 1
    assert result['neither_label'] == 1
    assert result['positive_minutes_missing_points'] == 1
    assert result['explicit_zero_points'] == 2
    assert result['explicit_negative_points'] == 1
    assert result['both_label_fraction_of_archive'] == 0.5
    pd.testing.assert_frame_equal(frame, original)


def test_empty_window_is_unknown_coverage_not_perfect_coverage():
    result = label_coverage(pd.DataFrame({'minutes': [], 'total': []}))
    assert result['archived_rows'] == 0
    assert result['both_label_fraction_of_archive'] is None
