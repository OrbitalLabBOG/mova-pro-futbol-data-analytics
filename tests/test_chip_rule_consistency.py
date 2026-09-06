from copy import deepcopy

from experiments.data_ground_truth.chip_rule_consistency import constraints, window


def source():
    return dict(game_settings={'squad_squadsize': 15}, game_config={'rules': {'squad_squadsize': 15}},
                element_types=[dict(id=i, squad_select=q) for i, q in enumerate([2, 5, 5, 3], 1)])


def test_future_impossible_squad_does_not_become_active_or_silently_repaired():
    chip = dict(start_event=20, stop_event=38, overrides={'rules': {'squad_squadsize': 16}})
    before = deepcopy(chip)
    result = constraints(source(), chip)
    assert result['status'] == 'inconsistent_squad_total'
    assert result['declared_squad_total'] == 16
    assert result['exact_role_quota_total'] == 15
    assert window(chip, 14) == 'future'
    assert window(chip, 20) == 'within_declared_window'
    assert chip == before


def test_unknown_roles_and_overrides_cannot_be_declared_consistent():
    s = source()
    assert constraints(s)['status'] == 'internally_consistent_squad_total'
    s['element_types'][0]['squad_select'] = None
    assert constraints(s)['status'] == 'unknown_role_quota'
    s = source()
    assert constraints(s, dict(overrides={'element_types': [{'id': 5}]}))['status'] == 'unsupported_override'
    s['game_config']['rules']['squad_squadsize'] = 16
    assert constraints(s)['status'] == 'conflicting_base_settings'
