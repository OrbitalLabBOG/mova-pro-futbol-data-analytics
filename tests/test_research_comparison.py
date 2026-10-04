from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('compare_agents', ROOT / 'experiments/research/compare_agents.py')
comparison = importlib.util.module_from_spec(spec)
spec.loader.exec_module(comparison)


def _write(root, run, *, limit=1000, tokens=500, version='1.10.0', subjects=2,
           context='focus_on_demand', source='sequential_live_fetch'):
    request = {'agent_version': version, 'agent_release': {
        'model': 'gpt-6-astra', 'reasoning_effort': 'medium',
        'output_schema': 'mova-research-brief-v2', 'codex_version': '0.153.4',
        'execution': 'app_server', 'context_profile': context, 'interactive_evidence': True},
        'experiment': {'source_method': source},
        'manifest': {'research_summary': {'focus': [{'element': i} for i in range(10)]}},
        'scope_policy': {'max_documents': 16}, 'quality_policy': 'research-claim-2026.09.5',
        'guardrails': {'agent_budget': {'job_tokens': limit}}}
    report = {'evaluated_at': '2026-09-29T00:00:00Z',
              'coverage': {'evidence_verified_subjects': subjects, 'coverage_ratio': subjects / 10,
                           'evidence_ratio': subjects / 10},
              'documents': [{'fetch_status': 'verified', 'publication_date_verified': True}],
              'signals': [{'player_element': 1, 'validation_status': 'accepted',
                           'quality': {'status': 'supported'}}], 'conflicts': []}
    receipt = {'model': 'gpt-6-astra', 'status': 'completed', 'input_tokens': tokens,
               'output_tokens': 0 if tokens is not None else None, 'duration_ms': 100}
    for relative, value in [(f'archive/{run}.request.json', request),
                            (f'archive/{run}.evaluation.json', report),
                            (f'receipts/{run}.attempt.finished.json', receipt),
                            (f'logs/{run}.attempt.context.json', {
                                'implementation_sha256': 'a'*64, 'context_sha256': 'b'*64})]:
        p = root / relative; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(value))
    p = root / f'logs/{run}.attempt.verification/checks.jsonl'
    p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps({'status': 'supported', 'reasons': []})+'\n')


def test_equal_budget_pair_with_coverage_gain_is_only_review_eligible(tmp_path):
    _write(tmp_path, 'baseline'); _write(tmp_path, 'candidate', subjects=4, version='1.11.0')
    result = comparison.compare(tmp_path, 'baseline', 'candidate')
    assert result['eligible_for_promotion_review'] is True
    assert result['autonomy_gate_satisfied'] is False
    assert result['candidate']['operational_import'] is False


@pytest.mark.parametrize('baseline,candidate,check', [
    ({'limit': 100}, {'subjects': 4, 'limit': 2000}, 'same_job_token_limit'),
    ({'tokens': 1500}, {'subjects': 4}, 'baseline_within_budget'),
    ({'tokens': None}, {'subjects': 4}, 'baseline_within_budget'),
    ({}, {'subjects': 4, 'tokens': None}, 'candidate_within_budget'),
    ({}, {'subjects': 4, 'tokens': 1500}, 'candidate_within_budget'),
    ({}, {'subjects': 4, 'context': 'different'}, 'same_context'),
    ({}, {'subjects': 4, 'source': 'frozen_web'}, 'same_source_method'),
    ({}, {'subjects': 3}, 'material_coverage_gain'),
])
def test_unfair_or_unmetered_comparison_cannot_be_eligible(tmp_path, baseline, candidate, check):
    _write(tmp_path, 'baseline', **baseline); _write(tmp_path, 'candidate', **candidate)
    result = comparison.compare(tmp_path, 'baseline', 'candidate')
    assert result['checks'][check] is False
    assert result['eligible_for_promotion_review'] is False
    assert result['autonomy_gate_satisfied'] is False


def test_missing_evaluation_never_fabricates_quality(tmp_path):
    _write(tmp_path, 'baseline'); _write(tmp_path, 'candidate')
    (tmp_path / 'archive/candidate.evaluation.json').unlink()
    result = comparison.compare(tmp_path, 'baseline', 'candidate')
    assert result['reason'] == 'evaluation_missing'
    assert result['eligible_for_promotion_review'] is False


def test_sealed_offline_corpus_uses_production_validators_and_no_calls():
    from experiments.research.replay_corpus import replay
    report = replay(ROOT / 'experiments/research/20260929-harness')
    assert report['status'] == 'pass'
    assert len(report['cases']) == 8
    assert report['silence_does_not_fill_coverage']
    assert report['external_calls'] == report['llm_calls'] == 0
    assert report['runtime_mutated'] is report['autonomy_gate_satisfied'] is False


def test_offline_replay_rejects_changed_source_corpus(tmp_path):
    import shutil
    from experiments.research.replay_corpus import replay
    root = ROOT / 'experiments/research/20260929-harness'
    for name in ('corpus.json', 'sources.json'): shutil.copy(root / name, tmp_path / name)
    with (tmp_path / 'sources.json').open('a') as stream: stream.write(' ')
    with pytest.raises(ValueError, match='hash mismatch'): replay(tmp_path)
