"""Offline contracts for MLflow integration (no MLflow server dependency)."""
import copy
import json
from pathlib import Path

import pytest
from experiments.benchmark.tracking import plan, sha, sync


def snapshot():
    return json.loads((Path(__file__).resolve().parents[1] /
        'experiments/benchmark/snapshots/v1/catalog.json').read_text())


def test_historical_tracking_is_stable_and_preserves_provenance():
    data = snapshot()
    rows = plan(data)
    assert rows == plan(copy.deepcopy(data))
    assert len(rows) == len({r['identity'] for r in rows})
    assert all(r['tags']['evidence_origin'] == 'historical_import' for r in rows)
    assert all(r['tags']['promotion_authorized'] == 'false' for r in rows)
    losing = [r for r in rows if r['tags'].get('source_experiment') == 'EXP-MOVA-2026-021'
              and r['tags'].get('variant') == 'participation' and r['tags'].get('aggregation') == 'summary']
    assert len(losing) == 1 and losing[0]['metrics']['mean_pva_38'] < 0


def test_evidence_change_creates_new_identity():
    data = snapshot()
    before = plan(data)
    data['groups'][0]['comparison_sha256'] = 'changed'
    after = plan(data)
    assert before[0]['identity'] != after[0]['identity']
    assert before[-1]['identity'] == after[-1]['identity']


def test_different_protocols_remain_different_experiments():
    rows = plan(snapshot())
    a = next(r for r in rows if r['experiment'].endswith('exp003-historical_holdout-v1'))
    b = next(r for r in rows if r['experiment'].endswith('exp021-external_diagnostic-v1'))
    assert a['experiment'] != b['experiment']


def test_executable_snapshot_rejected():
    data = snapshot()
    data['promotion_authorized'] = True
    with pytest.raises(ValueError):
        plan(data)


def test_finished_run_drift_is_not_silently_overwritten():
    from types import SimpleNamespace
    class Client:
        def get_experiment_by_name(self, name):
            return SimpleNamespace(experiment_id='1', lifecycle_stage='active')
        def search_runs(self, *args, **kwargs):
            return [SimpleNamespace(info=SimpleNamespace(status='FINISHED'),
                                    data=SimpleNamespace(metrics={'wrong': 1}))]
    with pytest.raises(ValueError, match='drift'):
        sync(Client(), plan(snapshot())[:1], 'tester', 'test')
