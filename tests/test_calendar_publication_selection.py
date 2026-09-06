from copy import deepcopy

import pytest

from experiments.data_ground_truth.calendar_publication_selection import choose


def calendar(repository='a', commit='2025-08-01T00:00:00Z'):
    return dict(season='2025-26', gw=1, repository=repository,
                source_committer_at=commit, available_at='2025-08-02T00:00:00Z',
                deadline='2025-08-03T00:00:00Z', normalized_sha256=repository,
                proof={'eligible_predeadline': True})


def test_selection_preserves_whole_latest_calendar_independent_of_order():
    older = calendar()
    newer = calendar('b', '2025-08-01T12:00:00Z')
    original = deepcopy([older, newer])
    assert choose([older, newer]) == choose([newer, older]) == [newer]
    assert [older, newer] == original
    assert choose([older, newer])[0] is newer


def test_selection_rejects_future_unproven_and_inconsistent_deadlines():
    for field, value in [('available_at', '2025-08-03T00:00:00Z'),
                         ('source_committer_at', '2025-08-02T01:00:00Z'),
                         ('proof', {'eligible_predeadline': False})]:
        invalid = calendar()
        invalid[field] = value
        with pytest.raises(ValueError, match='unproven or future'):
            choose([invalid])
    conflicting = calendar('b')
    conflicting['deadline'] = '2025-08-04T00:00:00Z'
    with pytest.raises(ValueError, match='deadline disagreement'):
        choose([calendar(), conflicting])
