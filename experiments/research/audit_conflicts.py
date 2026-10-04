#!/usr/bin/env python3
"""Review original sealed evidence; never adjudicate, fetch or mutate conflicts."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def audit(conflicts, documents, evidence_root):
    root = evidence_root.resolve(strict=True)
    findings = []
    for conflict in conflicts:
        if conflict.get('status') != 'unresolved':
            continue
        urls = set(json.loads(conflict['source_urls_json']))
        docs = [d for d in documents if d.get('research_run_id') == conflict['research_run_id']
                and d.get('source_url') in urls]
        reasons, evidence = [], []
        if {d['source_url'] for d in docs} != urls:
            reasons.append('original_sources_missing_from_inventory')
        for doc in docs:
            issues = []
            if doc.get('fetch_status') != 'verified':
                issues.append('original_fetch_unverified')
            excerpt = doc.get('excerpt')
            if not isinstance(excerpt, str) or not excerpt or hashlib.sha256(excerpt.encode()).hexdigest() != doc.get('excerpt_sha256'):
                issues.append('original_excerpt_missing_or_changed')
            artifact, sealed = None, {}
            try:
                artifact = Path(doc.get('artifact_path') or '').resolve(strict=True)
                if not artifact.is_relative_to(root) or not artifact.is_file() or artifact.stat().st_size > 1_048_576:
                    raise ValueError('invalid artifact location or size')
                raw = artifact.read_bytes()
                if hashlib.sha256(raw).hexdigest() != doc.get('artifact_sha256'):
                    raise ValueError('changed artifact')
                sealed = json.loads(raw)
                for field in ('document_id', 'research_run_id', 'source_url', 'excerpt_sha256'):
                    if sealed.get(field) != doc.get(field):
                        raise ValueError('artifact provenance mismatch')
            except (OSError, ValueError, TypeError):
                issues.append('original_artifact_missing_changed_or_unbound')
            if not doc.get('published_at') or sealed.get('publication_date_verified') is not True:
                issues.append('original_publication_date_unverified')
            reasons.extend(issues)
            evidence.append({'document_id': doc['document_id'], 'fetch_status': doc.get('fetch_status'),
                             'published_at': doc.get('published_at'),
                             'artifact_sha256': doc.get('artifact_sha256'),
                             'publication_date_verified': sealed.get('publication_date_verified') is True,
                             'issues': issues})
        findings.append({'conflict_id': conflict['conflict_id'], 'cycle_id': conflict['cycle_id'],
                         'research_run_id': conflict['research_run_id'], 'subject': conflict['subject'],
                         'source_count': len(urls), 'original_documents': evidence,
                         'classification': 'evidence_insufficient' if reasons else 'semantic_review_required',
                         'reasons': sorted(set(reasons)), 'resolution_performed': False,
                         'next_action': 'Preserve conflict; recover original evidence and establish exact period before supervised adjudication.'})
    return {'schema': 'mova-research-conflict-audit-v1',
            'generated_at': datetime.now(timezone.utc).isoformat(), 'findings': findings,
            'external_calls': 0, 'runtime_mutated': False, 'conflicts_resolved': 0,
            'limitations': ['Inventory truncation is treated as missing evidence, never as absence of conflict.',
                           'Verified fetch/hash/date does not prove that claims are semantically compatible.',
                           'Fresh web content cannot replace missing original evidence or backfill timestamps.']}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inventory', type=Path, required=True)
    p.add_argument('--evidence-root', type=Path, required=True)
    args = p.parse_args(); inventory = json.loads(args.inventory.read_text())
    print(json.dumps(audit(inventory['conflicts'], inventory['documents'], args.evidence_root),
                     ensure_ascii=False, indent=2))
