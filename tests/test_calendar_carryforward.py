from copy import deepcopy

import pytest

from experiments.data_ground_truth.calendar_carryforward import differences, select_previous


def calendar():
    return dict(season='2025-26',gw=1,source_committer_at='2025-08-01T00:00:00Z',
                available_at='2025-08-01T01:00:00Z',deadline='2025-08-02T00:00:00Z',
                repository='fixture',proof={'eligible_predeadline':True})


def test_carryforward_enforces_age_season_and_strict_publication_bounds():
    row=calendar();target=dict(season='2025-26',gw=2,deadline='2025-08-15T00:00:00Z')
    assert select_previous([row],target,336) is row
    assert select_previous([row],target,335) is None
    for field,value in [('season','2024-25'),('gw',2),('available_at',row['deadline']),
                        ('proof',{'eligible_predeadline':False})]:
        invalid=dict(row,**{field:value})
        assert select_previous([invalid],target) is None
    with pytest.raises(ValueError):select_previous([row],target,0)


def test_delta_keeps_both_values_and_rejects_identity_changes():
    old=[dict(id=1,code=10,team_h=1,team_a=2,event=3,kickoff_time='2025-08-20T12:00:00Z')]
    newer=[dict(old[0],event=4,kickoff_time='2025-08-27T12:00:00Z')]
    original=deepcopy(old)
    delta=differences(old,newer,'2025-08-15T00:00:00Z')
    assert {d['field'] for d in delta}=={'event','kickoff_time'}
    assert all(d['future_or_unknown'] for d in delta)
    assert old==original
    with pytest.raises(ValueError,match='identity'):differences(old,[dict(newer[0],team_a=3)],'2025-08-15T00:00:00Z')
    with pytest.raises(ValueError,match='population'):differences(old,[],'2025-08-15T00:00:00Z')


def test_latest_proven_source_selected_without_using_later_diagnostic():
    old=calendar();recent=dict(old,source_committer_at='2025-08-01T00:30:00Z')
    target=dict(season='2025-26',gw=2,deadline='2025-08-03T00:00:00Z')
    assert select_previous([recent,old],target) is recent
    assert select_previous([old,recent],target) is recent
