from experiments.data_ground_truth.annual_defensive_reference import FIELDS, compare_cells, consensus


def observation(value=0, status='valid'):
    return dict(cells={f: dict(status=status, value=value) for f in FIELDS})


def test_conflicting_versions_never_majority_vote_or_become_zero():
    result = consensus([observation(0), observation(0), observation(8)])
    assert result['tackles']['status'] == 'conflict'
    assert result['tackles']['value'] is None
    assert result['tackles']['observed_values'] == [0, 8]
    assert compare_cells(observation(), result)['tackles']['status'] == 'annual_conflict'


def test_absent_and_zero_retain_distinct_source_states():
    result = consensus([observation(None, 'absent'), observation(0)])
    assert result['recoveries']['status'] == 'observed_value'
    assert result['recoveries']['value'] == 0
    assert result['recoveries']['source_states'] == {'absent': 1, 'valid': 1}
    unknown = consensus([observation(None, 'empty')])
    assert unknown['recoveries']['status'] == 'unknown'
    assert compare_cells(observation(), unknown)['recoveries']['status'] == 'annual_unknown'


def test_snapshot_preserved_on_difference_or_missing_reference():
    snapshot = observation(7)
    result = compare_cells(snapshot, consensus([observation(8)]))
    assert result['tackles'] == dict(status='different', snapshot_value=7, annual_value=8)
    assert snapshot['cells']['tackles']['value'] == 7
    assert compare_cells(snapshot, None)['tackles']['status'] == 'no_annual_reference'
