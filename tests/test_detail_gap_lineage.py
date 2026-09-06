from experiments.data_ground_truth.detail_gap_lineage import inspect_key


def test_unidentified_row_is_preserved_when_exact_key_absent():
    result = inspect_key([(2, {'player_id': '', 'player_name': 'A'})], '12')
    assert result['status'] == 'absent_exact_key'
    assert result['unidentified_rows'] == 1
    assert result['matches'] == []


def test_duplicate_exact_identity_is_not_recovery():
    rows = [(2, {'player_id': '12', 'rating': '0'}), (3, {'player_id': '12', 'rating': '7'})]
    result = inspect_key(rows, '12')
    assert result['status'] == 'ambiguous_exact_key'
    assert result['matches'] == rows


def test_observed_zero_and_empty_are_not_rewritten():
    rows = [(2, {'player_id': '12', 'rating': '0', 'other': ''})]
    assert inspect_key(rows, '12')['matches'] == rows
