#!/usr/bin/env python3
"""Prepare metadata for a pair without enqueueing, reserving or exposing the request."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMMON_FIELDS = ('model', 'reasoning_effort', 'interactive_evidence', 'quality_policy',
                 'output_schema', 'execution', 'logical_token_guard', 'context_profile',
                 'execution_timeout_ms', 'search_window_days', 'codex_version',
                 'evidence_handoff', 'discovery_profile')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode()).hexdigest()


def positive(value, label):
    if type(value) is not int or value <= 0:
        raise ValueError(f'{label} must be a positive integer')
    return value


def prepare(request, cost, baseline='1.10.0', candidate='1.12.0'):
    if request.get('schema') != 'mova-research-request-v1':
        raise ValueError('unsupported request schema')
    if digest({k: v for k, v in request.items() if k != 'request_sha256'}) != request.get('request_sha256'):
        raise ValueError('sealed request hash mismatch')
    registry = json.loads((ROOT/'mova_fpl/ops/agent_releases.json').read_text())['agents']['researcher']
    if baseline == candidate or baseline not in registry['versions'] or candidate not in registry['versions']:
        raise ValueError('pair requires two registered versions')
    a, b = (registry['versions'][v] for v in (baseline, candidate))
    differences = {k: [a.get(k), b.get(k)] for k in sorted(a.keys() | b.keys()) if a.get(k) != b.get(k)}
    checks = {f'same_{k}': a.get(k) is not None and a.get(k) == b.get(k) for k in COMMON_FIELDS}
    policy = cost.get('policy') or {}
    job_limit = positive(policy.get('job_tokens'), 'current job limit')
    original_limit = positive(request['guardrails']['agent_budget']['job_tokens'], 'request job limit')
    checks['same_sealed_job_limit'] = original_limit == job_limit
    # Maximum settlement exposure, not the smaller up-front reservation.
    required_tokens, required_uses = 3 * job_limit, 3
    checks['no_orphan_reservations'] = (cost.get('orphaned_reservations') or {}).get('status') == 'none'
    for scope in ('gameweek', 'month'):
        row = cost.get(scope) or {}
        checks[f'{scope}_within_budget'] = row.get('status') == 'within_budget'
        checks[f'{scope}_capacity_after_operational_reserve'] = (
            type(row.get('remaining_tokens')) is int and row['remaining_tokens'] >= required_tokens
            and type(row.get('remaining_uses')) is int and row['remaining_uses'] >= required_uses)
    focus = request.get('manifest', {}).get('research_summary', {}).get('focus', [])
    ids = {r['element'] for r in focus}
    files = ('deploy/research/codex-worker.mjs', 'deploy/research/research-context.mjs',
             'deploy/research/evidence-tool.py', 'mova_fpl/ops/agent_releases.json')
    implementation = {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
                      for name in files}
    return {
        'schema': 'mova-research-pair-preparation-v1',
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'status': 'prepared_for_recheck' if all(checks.values()) else 'deferred',
        'checks': checks, 'versions': {'baseline': baseline, 'candidate': candidate, 'active': registry['active']},
        'intentional_differences': differences, 'request_sha256': request['request_sha256'],
        'manifest_sha256': digest(request['manifest']), 'scope_policy': request['scope_policy'],
        'focus_subjects': len(ids), 'common_contract': {k: a.get(k) for k in COMMON_FIELDS},
        'implementation_sha256s': implementation,
        'budget': {'per_arm_maximum_tokens': job_limit, 'pair_maximum_tokens': 2*job_limit,
                   'preserved_operational_tokens': job_limit, 'required_available_tokens': required_tokens,
                   'required_available_uses': required_uses,
                   'available': {s: {k: cost.get(s, {}).get(k) for k in ('remaining_tokens','remaining_uses')}
                                 for s in ('gameweek', 'month')}},
        'enqueued': False, 'budget_reserved': False, 'external_calls': 0, 'runtime_mutated': False,
        'limitations': ['Recheck live capacity and seal a fresh common manifest before enqueue.',
                       'Token guard is reactive, not a physical inference cutoff.',
                       'This compares the combined agenda/allocation change, not allocation alone.',
                       'Preparation is not quality evidence, authority or multi-GW acceptance.'],
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', required=True, type=Path)
    parser.add_argument('--cost-report', required=True, type=Path)
    parser.add_argument('--baseline', default='1.10.0')
    parser.add_argument('--candidate', default='1.12.0')
    args = parser.parse_args()
    print(json.dumps(prepare(json.loads(args.request.read_text()), json.loads(args.cost_report.read_text()),
                             args.baseline, args.candidate), ensure_ascii=False, indent=2))
