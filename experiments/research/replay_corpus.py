"""Offline replay of sealed excerpts through the production research validators."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

from mova_fpl.ops.strategy import StrategicContextService as Validator


def replay(root: Path) -> dict:
    corpus = json.loads((root / 'corpus.json').read_text())
    raw = (root / 'sources.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != corpus['sources_sha256']:
        raise ValueError('source corpus hash mismatch')
    sources = json.loads(raw)
    for source in sources:
        if hashlib.sha256(source['excerpt'].encode()).hexdigest() != source['excerpt_sha256']:
            raise ValueError('excerpt hash mismatch')
    by_id = {s['document_id']: s for s in sources}
    catalog = {int(row[0]): row[1] for row in corpus['catalog']}
    results = []
    for case in corpus['cases']:
        source = by_id[case['document_id']]
        observed = datetime.fromisoformat(case.get('observed_at', source['observed_at']).replace('Z', '+00:00'))
        cutoff = datetime.fromisoformat(case.get('cutoff_at', corpus['cutoff_at']).replace('Z', '+00:00'))
        name = catalog[case['element']]
        raw_signal = {'subject_name': name, 'player_element': case['element'],
                      'claim_type': case['claim_type'], 'claim_text': 'Offline contract fixture; inspect the sealed excerpt.',
                      'direction': 'neutral', 'confidence': .8, 'source_urls': [source['source_url']],
                      'corroboration_status': 'official_primary' if source['source_tier']=='official' else 'unknown',
                      'expires_at': (observed + timedelta(days=2)).isoformat()}
        keys = {(name.casefold(), case['claim_type'])} if case.get('conflicted') else set()
        signal = Validator._validate_signals(
            [raw_signal], {source['source_url']: source}, keys, observed,
            require_verified=True, catalog=catalog, cutoff=cutoff,
            require_freshness=True, quality_policy='research-claim-2026.09.5')[0]
        passed = (signal['validation_status']==case['expected_validation']
                  and signal['quality']['reason']==case['expected_reason'])
        results.append({'case_id': case['id'], 'pass': passed,
                        'validation_status': signal['validation_status'],
                        'quality_reason': signal['quality']['reason'],
                        'unresolved_conflict': signal['conflict_status']=='unresolved'})
    # A named appearance may establish coverage, never an injury/fitness claim.
    focus = [{'element': 12}, {'element': 411}]
    source = by_id['document_ee178e710c3fbc209604de3c445f528f']
    coverage = Validator._validate_coverage({'subjects': [
        {'player_element': 12, 'status': 'no_material_update', 'source_urls': [source['source_url']], 'note': 'Mention only.'},
        {'player_element': 411, 'status': 'no_material_update', 'source_urls': [], 'note': 'Search silence is not evidence.'},
    ]}, focus, {source['source_url']: source}, [], legacy=False, catalog=catalog,
       fetched_at=datetime.fromisoformat(source['observed_at']),
       cutoff=datetime.fromisoformat(corpus['cutoff_at'].replace('Z', '+00:00')), require_freshness=True)
    silence_ok = coverage['subjects'][1]['status']=='not_checked' and coverage['evidence_verified_subjects']==1
    return {'schema': 'mova-research-offline-replay-v1',
            'status': 'pass' if all(r['pass'] for r in results) and silence_ok else 'fail',
            'sources': len(sources), 'cases': results, 'coverage': coverage,
            'silence_does_not_fill_coverage': silence_ok, 'llm_calls': 0, 'external_calls': 0,
            'runtime_mutated': False, 'autonomy_gate_satisfied': False,
            'limitations': corpus['limitations']}


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('root', type=Path)
    report=replay(parser.parse_args().root); print(json.dumps(report,ensure_ascii=False,indent=2))
    raise SystemExit(0 if report['status']=='pass' else 1)
