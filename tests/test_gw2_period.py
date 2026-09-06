import pandas as pd

from experiments.data_ground_truth.gw2_period import FIELDS, reference


def row(gw, element, code, minutes):
    return {**{f: 0 for f in FIELDS}, 'gw': gw, 'element': element,
            'official_player_code': code, 'minutes': minutes}


def test_reference_excludes_future_weeks_and_preserves_missing_players():
    refs = reference(pd.DataFrame([row(1, 1, 10, 80), row(2, 1, 10, 90),
                                   row(2, 2, 20, 90)]))
    assert refs[10]['values']['minutes'] == 80
    assert 20 not in refs


def test_reference_preserves_unknown_and_ambiguous_components():
    refs = reference(pd.DataFrame([row(1, 1, 10, None), row(1, 2, 20, 5),
                                   row(1, 3, 20, 10)]))
    assert refs[10]['values']['minutes'] is None
    assert refs[20]['status'] == 'ambiguous_reference_code'
