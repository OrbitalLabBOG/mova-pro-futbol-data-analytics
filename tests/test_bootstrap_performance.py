import gzip
import json

import pytest

from experiments.data_ground_truth import bootstrap_performance as bp
from experiments.data_ground_truth.raw import digest


@pytest.mark.parametrize('field,value,status,result', [
    ('minutes', 0, 'valid', 0), ('minutes', True, 'invalid_type', None),
    ('minutes', -1, 'negative', None), ('minutes', '1.5', 'fractional_count', None),
    ('minutes', None, 'null', None), ('minutes', 'NaN', 'nonfinite', None),
    ('expected_goals', '1.25', 'valid', '1.25'),
    ('expected_goals', 'Infinity', 'nonfinite', None),
    ('expected_goals', 'n/a', 'invalid_number', None),
    ('total_points', -2, 'valid', -2), ('bps', -3, 'valid', -3),
])
def test_domains_preserve_zero_signed_points_and_missingness(field, value, status, result):
    assert bp.cell({field: value}, field) == dict(status=status, value=result)
    assert bp.cell({}, field) == dict(status='absent', value=None)


def fixture(tmp_path, monkeypatch):
    raw = tmp_path/'raw'; selection = tmp_path/'selection'
    (raw/'objects').mkdir(parents=True); selection.mkdir()
    candidates, records = [], []
    for gw, minutes in [(1, 90), (2, 80)]:
        c = dict(season='2025-26', gw=gw, deadline=f'2025-08-{10+gw}T00:00:00Z',
                 source_claimed_at=f'2025-08-{gw:02d}T00:00:00', path=str(gw))
        snapshot = dict(candidate=c, elements=[dict(id=1, code=100, element_type=2, minutes=minutes),
                                               dict(id=2, code=200, element_type=5, minutes=99)])
        data = json.dumps(snapshot).encode(); sha = digest(data)
        (raw/'objects'/sha).write_bytes(data)
        records.append(dict(path=str(gw), sha256=sha)); candidates.append(dict(c, sha256=sha))
    manifest = json.dumps(dict(records=records, errors=[])).encode()
    (raw/'manifest.json').write_bytes(manifest)
    data = json.dumps(candidates).encode()
    (selection/'nominal_deadline_candidates.json').write_bytes(data)
    (selection/'report.json').write_text(json.dumps(dict(manifest_sha256=digest(manifest), errors=[],
                      artifacts={'nominal_deadline_candidates.json': digest(data)})))
    monkeypatch.setattr(bp, 'decode', json.loads)
    monkeypatch.setattr(bp, 'inspect', lambda s, p: (None, [s['candidate']]))
    return raw, selection


def test_decreases_are_preserved_and_managers_excluded(tmp_path, monkeypatch):
    raw, selection = fixture(tmp_path, monkeypatch)
    out = tmp_path/'out'; report = bp.build(raw, selection, out)
    rows = [json.loads(x) for x in gzip.decompress((out/'performance.jsonl.gz').read_bytes()).splitlines()]
    assert [r['cells']['minutes']['value'] for r in rows] == [90, 80]
    assert report['anomalies'] == {'cumulative_decrease': 1}
    assert report['coverage']['2025-26']['managers_excluded'] == 2
    assert all(r['available_at'] is None and not r['eligible_training'] for r in rows)
    bp.build(raw, selection, tmp_path/'repeat')
    for name in ('report.json', 'performance.jsonl.gz', 'anomalies.json'):
        assert (out/name).read_bytes() == (tmp_path/'repeat'/name).read_bytes()


def test_source_tampering_rejected_before_decode(tmp_path, monkeypatch):
    raw, selection = fixture(tmp_path, monkeypatch)
    obj = next((raw/'objects').iterdir()); obj.write_bytes(b'altered')
    with pytest.raises(ValueError):
        bp.build(raw, selection, tmp_path/'out')
