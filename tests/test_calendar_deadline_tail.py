import pytest
from experiments.data_ground_truth.calendar_deadline_tail import hours


def test_tail_starts_after_prior_search_and_keeps_partial_deadline_hour():
    c=dict(committer_at='2022-04-07T14:14:36Z',deadline='2022-04-08T17:30:00Z')
    assert hours(c)==['2022-04-08-15','2022-04-08-16','2022-04-08-17']
    assert hours(dict(c,deadline='2022-04-08T17:00:00Z'))==['2022-04-08-15','2022-04-08-16']


def test_unreviewed_long_interval_is_not_silently_truncated():
    with pytest.raises(ValueError,match='bound'):
        hours(dict(committer_at='2022-04-01T00:00:00Z',deadline='2022-04-08T17:00:00Z'))
