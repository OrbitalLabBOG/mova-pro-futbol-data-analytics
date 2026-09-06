import pytest

from experiments.data_ground_truth.preseason_supplemental import FIELDS, code_key, compare_row, references


def match(season='2023-24', code=99, element=7, fixture=1):
    return dict(season=season, official_player_code=code, element=element, fixture=fixture,
                cells={f: dict(status='valid', value=2) for f in FIELDS})


def snapshot():
    return dict(season='2024-25', source_code=99, element=88, source_sha256='x', deadline='x',
                cells={f: dict(status='valid', value=2) for f in FIELDS})


def test_only_prior_season_code_matches_despite_element_reuse():
    refs = references([match(code='99'), match('2024-25', fixture=2), match(code=123, element=88)])
    result = compare_row(snapshot(), refs, {'2023-24'})
    assert all(v['status'] == 'equal' for v in result['comparisons'].values())
    row = snapshot(); row['source_code'] = 456
    result = compare_row(row, refs, {'2023-24'})
    assert all(v['status'] == 'no_reference_code' for v in result['comparisons'].values())


def test_partial_and_ambiguous_references_remain_unknown():
    first = match(); second = match(fixture=2)
    second['cells']['starts'] = dict(status='absent', value=None)
    refs = references([first, second])
    assert compare_row(snapshot(), refs, {'2023-24'})['comparisons']['starts']['status'] == 'unknown_reference_component'
    assert compare_row(snapshot(), refs, set())['comparisons']['starts']['status'] == 'incomplete_reference_season'
    refs = references([first, match(element=8)])
    assert compare_row(snapshot(), refs, {'2023-24'})['comparisons']['starts']['status'] == 'ambiguous_reference_code'


def test_duplicate_match_rejected():
    with pytest.raises(ValueError, match='duplicate'):
        references([match(), match()])


@pytest.mark.parametrize('value', [True, 99.5, '99.0', 'nan', -1])
def test_invalid_identity_never_coerced_to_another_player(value):
    with pytest.raises(ValueError, match='source code'):
        code_key(value)
