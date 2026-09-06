from experiments.data_ground_truth.lineup_integrity import starter_difference


def test_equal_size_lineups_can_have_wrong_starters():
    result = starter_difference({'a', 'b'}, {'b', 'c'})
    assert result == {'extra': ['a'], 'missing': ['c'], 'status': 'different'}


def test_starter_set_comparison_does_not_depend_on_order():
    assert starter_difference({'b', 'a'}, {'a', 'b'}) == {'extra': [], 'missing': [], 'status': 'equal'}


def test_unmapped_historical_starter_prevents_recovery_claim():
    from experiments.data_ground_truth.lineup_integrity import historical_starters
    rows = [{'player_id': '1', 'is_starting': 'True'}, {'player_id': '', 'is_starting': 'True'}]
    result = historical_starters(rows, {'1': '101'}, {'101'})
    assert result['comparison']['status'] == 'unknown'
    assert result['unknown_players'] == 1
    assert result['recovery_candidate'] is False
