"""Benchmark comparisons must not turn missing/altered evidence into progress."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from experiments.benchmark.run import build, paired_rows, safe_path


def test_paired_progress_preserves_losses_and_control():
    rows = [{'season': s, 'variant': v, 'points': p}
            for s, a, b in [('2023-24', 100, 130), ('2024-25', 200, 150)]
            for v, p in [('base', a), ('new', b)]]
    result = paired_rows(rows, 'base')[0]
    assert result['pva_38_by_season'] == {'2023-24': 30, '2024-25': -50}
    assert result['mean_pva_38'] == -10
    assert (result['wins'], result['losses']) == (1, 1)


@pytest.mark.parametrize('rows', [
    [{'season': 's', 'variant': 'new', 'points': 20}],
    [{'season': 's', 'variant': 'base', 'points': 20}] * 2,
    [{'season': 's', 'variant': 'base', 'points': float('nan')}],
    [{'season': 's', 'variant': 'base', 'points': True}],
    [{'season': 's', 'variant': 'base', 'points': 1},
     {'season': 't', 'variant': 'new', 'points': 2}],
])
def test_invalid_comparisons_rejected(rows):
    with pytest.raises(ValueError):
        paired_rows(rows, 'base')


def fixture_registry(tmp_path):
    directory = tmp_path / 'EXP-MOVA-TEST'
    directory.mkdir()
    (directory / 'manifest.json').write_text('{}')
    obj = {'totals': [{'season': 's', 'variant': 'base', 'points': 10},
                      {'season': 's', 'variant': 'new', 'points': 20}]}
    (directory / 'selection.json').write_text(json.dumps(obj))
    registry = {'benchmark_version': 'test-v1', 'limitations': [], 'groups': [
        {'id': 'test', 'experiment': directory.name, 'phase': 'development',
         'files': ['selection.json'], 'adapter': 'totals', 'control': 'base',
         'description': 'test', 'seasons': ['s']}]}
    return registry, directory


def test_manifest_changes_identity_and_missing_experiments_stay_visible(tmp_path):
    registry, directory = fixture_registry(tmp_path)
    (tmp_path / 'EXP-MOVA-INCOMPLETE').mkdir()
    before = build(tmp_path, registry)
    (directory / 'manifest.json').write_text('{"seed": 2}')
    after = build(tmp_path, registry)
    assert before['groups'][0]['comparison_sha256'] != after['groups'][0]['comparison_sha256']
    incomplete = next(c for c in after['catalog'] if c['experiment'].endswith('INCOMPLETE'))
    assert incomplete['evidence_status'] == 'no_top_level_metadata'
    assert after['global_ranking'] is None
    assert after['promotion_authorized'] is False


def test_bootstrap_for_different_comparison_rejected(tmp_path):
    registry, directory = fixture_registry(tmp_path)
    path = directory / 'selection.json'
    obj = json.loads(path.read_text())
    obj['bootstrap'] = {'observed_by_season': {'s': 99}}
    path.write_text(json.dumps(obj))
    registry['groups'][0]['uncertainty_paths'] = {'new': ['bootstrap']}
    with pytest.raises(ValueError, match='different comparisons'):
        build(tmp_path, registry)


def test_cli_check_detects_drift_and_refuses_overwrite(tmp_path):
    root = tmp_path / 'inputs'
    root.mkdir()
    registry, directory = fixture_registry(root)
    config = tmp_path / 'registry.json'
    config.write_text(json.dumps(registry))
    cmd = [sys.executable, '-m', 'experiments.benchmark.run', '--root', str(root),
           '--registry', str(config), '--output', str(tmp_path / 'snapshot')]
    assert subprocess.run(cmd, capture_output=True).returncode == 0
    assert subprocess.run(cmd + ['--check'], capture_output=True).returncode == 0
    assert subprocess.run(cmd, capture_output=True).returncode != 0
    (directory / 'manifest.json').write_text('{"changed": true}')
    assert subprocess.run(cmd + ['--check'], capture_output=True).returncode != 0


def test_replay_missing_week_rejected(tmp_path):
    registry, directory = fixture_registry(tmp_path)
    registry['groups'][0]['adapter'] = 'replays'
    (directory / 'selection.json').write_text(json.dumps({'gameweeks': [], 'total': 0}))
    with pytest.raises(ValueError, match='GW1..38'):
        build(tmp_path, registry)


def test_paths_cannot_escape_evidence_root(tmp_path):
    with pytest.raises(ValueError):
        safe_path(tmp_path, '../outside.json')


def test_shipped_report_and_portable_snapshot_agree():
    from experiments.benchmark.run import render
    root = Path(__file__).resolve().parents[1] / 'experiments/benchmark/snapshots/v1'
    data = json.loads((root / 'catalog.json').read_text())
    assert render(data) == (root / 'REPORT.md').read_text()
    for group in data['groups']:
        for row in group['rows']:
            for season in row['seasons']:
                assert row['pva_38_by_season'][season] == (
                    row['candidate_points'][season] - row['control_points'][season])
