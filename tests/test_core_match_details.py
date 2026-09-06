from experiments.data_ground_truth.core_match_details import field_coverage, key_status, paths


def test_missing_fields_empty_and_explicit_zero_are_distinct():
    result = field_coverage([{'blocks': ''}, {'blocks': '0'}, {'other': '1'}])
    assert result['blocks'] == {'empty': 1, 'populated': 1, 'absent': 1}


def test_event_identity_requires_all_key_components():
    assert key_status({'match_id': 'm', 'shot_index': ''}, ('match_id', 'shot_index')) is None
    assert key_status({'match_id': 'm'}, ('match_id', 'shot_index')) is None
    assert key_status({'match_id': 'm', 'shot_index': '1'}, ('match_id', 'shot_index')) == ('m', '1')
    assert len(paths()) == len(set(paths())) == 304
    assert all('/By Tournament/Premier League/' in p for p in paths())


def test_incomplete_download_manifest_fails_before_reading_reference(tmp_path):
    import json
    import pytest
    from experiments.data_ground_truth.core_match_details import build
    (tmp_path / 'manifest.json').write_text(json.dumps({'errors': [], 'records': []}))
    with pytest.raises(ValueError, match='incomplete or duplicate'):
        build(tmp_path, tmp_path / 'unread_reference', tmp_path / 'out')
    assert not (tmp_path / 'out').exists()


def test_duplicate_path_cannot_substitute_for_missing_table(tmp_path):
    import json
    import pytest
    from experiments.data_ground_truth.core_match_details import build
    records = [{'path': path} for path in paths()]
    records[-1] = records[0]
    (tmp_path / 'manifest.json').write_text(json.dumps({'errors': [], 'records': records}))
    with pytest.raises(ValueError, match='incomplete or duplicate'):
        build(tmp_path, tmp_path / 'unread_reference', tmp_path / 'out')
