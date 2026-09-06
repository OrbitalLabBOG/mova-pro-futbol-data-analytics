import pandas as pd
import pytest

from experiments.data_ground_truth.preseason_performance import FIELDS, compare, totals


def frame():
    return pd.DataFrame([dict(official_player_code=10, element=1, **{f: 1 for f in FIELDS}),
                         dict(official_player_code=10, element=1, **{f: 2 for f in FIELDS})])


def test_partial_totals_stay_unknown_and_signed_points_preserved():
    f = frame(); f.loc[0, 'minutes'] = None; f.loc[0, 'total_points'] = -4
    result = totals(f)[10]
    assert result['values']['minutes'] is None
    assert result['values']['total_points'] == -2
    row = {'cells': {f: dict(status='valid', value=3) for f in FIELDS}}
    verdict = compare(row, result)
    assert verdict['fields']['minutes']['status'] == 'incomplete_prior_total'
    assert verdict['fields']['total_points']['status'] == 'different'
    assert verdict['status'] == 'different'


def test_ambiguous_codes_are_not_aggregated_into_a_person():
    f = frame(); f.loc[1, 'element'] = 2
    assert totals(f)[10]['status'] == 'ambiguous_reference_code'
    assert compare({'cells': {}}, totals(f)[10])['status'] == 'ambiguous_reference_code'
    assert compare({'cells': {}}, None)['status'] == 'no_prior_reference_code'


def test_absent_snapshot_values_do_not_become_zero_matches():
    verdict = compare({'cells': {}}, totals(frame())[10])
    assert verdict['status'] == 'no_comparable_fields'
    assert all(v['status'] == 'snapshot_absent' for v in verdict['fields'].values())


@pytest.mark.parametrize('bad', [1.5, float('inf'), float('-inf')])
def test_invalid_reference_counts_cannot_be_silently_truncated(bad):
    f = frame().astype({'minutes': float}); f.loc[0, 'minutes'] = bad
    with pytest.raises(ValueError, match='integral'):
        totals(f)


def test_build_compares_each_snapshot_only_to_its_own_prior_season(tmp_path, monkeypatch):
    import gzip
    import json
    from experiments.data_ground_truth import preseason_performance as module
    from experiments.data_ground_truth.raw import digest
    root = tmp_path/'performance'; package = tmp_path/'package'
    root.mkdir(); package.mkdir()
    rows = []
    partitions = []
    for season, prior, value in [('2022-23', '2021-22', 3), ('2023-24', '2022-23', 6)]:
        f = frame()
        if value == 6:
            for field in FIELDS:
                f[field] *= 2
        filename = prior+'.csv'; f.to_csv(package/filename, index=False)
        partitions.append(dict(season=prior, file=filename))
        rows.append(dict(season=season, gw=1, element=1, source_code=10,
                         source_sha256='fixture', deadline=season,
                         cells={field: dict(status='valid', value=value) for field in FIELDS}))
    payload = gzip.compress(('\n'.join(json.dumps(r) for r in rows)).encode())
    (root/'performance.jsonl.gz').write_bytes(payload)
    (root/'report.json').write_text(json.dumps(dict(artifacts={'performance.jsonl.gz': digest(payload)})))
    monkeypatch.setattr(module, 'verify', lambda p: dict(dataset_id='fixture', partitions=partitions))
    result = module.build(root, package, tmp_path/'out')
    assert result['rows'] == 2
    assert all(c['players'] == 1 and c['statuses'] == {'all_compared_equal': 1}
               for c in result['coverage'].values())
