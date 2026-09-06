from copy import deepcopy

import pytest

from experiments.data_ground_truth.joint_coverage import BASIC, EXPECTED, combine


def evidence():
    target = dict(season='2025-26', gw=2, deadline='2025-08-22T17:30:00Z', sha256='a' * 64)
    proof = dict(target, source_sha256=target['sha256'], eligible_predeadline=True,
                 available_at='2025-08-22T16:00:00Z')
    calendar = dict(target, available_at='2025-08-22T15:00:00Z',
                    source_clock_age_hours=4, source_clock_kind='git_committer_at')
    screen = dict(season='2025-26', gw=2, rows=2, published=True,
                  fields={f: {'screen_pass': 2} for f in BASIC + EXPECTED})
    return [target], [proof], [calendar], [screen], [dict(season='2025-26', rows=30000)]


def test_partial_field_and_missing_calendar_do_not_become_complete_season():
    args = evidence()
    args[3][0]['fields']['expected_goals'] = {'screen_pass': 1, 'review_required': 1}
    rows, seasons = combine(*args)
    assert rows[0]['joint_basic_screen'] is True
    assert rows[0]['joint_expected_screen'] is False
    assert seasons[0]['target_universe_is_full_season'] is False
    args[2].clear()
    rows, seasons = combine(*args)
    assert rows[0]['joint_basic_screen'] is False
    assert rows[0]['calendar_source_clock_age_hours'] is None
    assert seasons[0]['missing_joint_gws'] == [2]
    assert rows[0]['training_admitted'] is False


@pytest.mark.parametrize('failure', ['late', 'deadline', 'digest', 'duplicate', 'population'])
def test_incompatible_evidence_is_rejected(failure):
    args = evidence()
    if failure == 'late':
        args[2][0]['available_at'] = args[0][0]['deadline']
    elif failure == 'deadline':
        args[2][0]['deadline'] = '2025-08-23T17:30:00Z'
    elif failure == 'digest':
        args[1][0]['source_sha256'] = 'b' * 64
    elif failure == 'duplicate':
        args[1].append(deepcopy(args[1][0]))
    else:
        args[3][0]['fields']['minutes'] = {'screen_pass': 1}
    with pytest.raises(ValueError):
        combine(*args)
