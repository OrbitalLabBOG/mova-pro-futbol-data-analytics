#!/usr/bin/env python3
"""Compare sealed paired evaluations; experimental results never certify a GW gate."""
import argparse
import hashlib
import json
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def summarize(root, run_id):
    request=json.loads((root/'archive'/f'{run_id}.request.json').read_text())
    path=root/'archive'/f'{run_id}.evaluation.json'
    report=json.loads(path.read_text())
    contexts=list((root/'logs').glob(f'{run_id}.*.context.json'))
    receipts=[json.loads(p.read_text()) for p in (root/'receipts').glob(f'{run_id}.*.finished.json')]
    checks=[json.loads(line) for p in (root/'logs').glob(f'{run_id}.*.verification/checks.jsonl')
            for line in p.read_text().splitlines()]
    tokens=sum(int(r.get('input_tokens') or 0)+int(r.get('output_tokens') or 0) for r in receipts)
    exact=bool(receipts) and all(r.get('input_tokens') is not None and r.get('output_tokens') is not None for r in receipts)
    useful=report['coverage'].get('evidence_verified_subjects',0)
    return {'run_id':run_id,'agent_version':request['agent_version'],
        'manifest_sha256':digest(request['manifest']),'scope_policy':request['scope_policy'],
        'quality_policy':request['quality_policy'],'evaluated_at':report['evaluated_at'],
        'evaluation_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'documents':len(report['documents']),
        'verified_documents':sum(d.get('fetch_status')=='verified' for d in report['documents']),
        'dated_documents':sum(bool(d.get('publication_date_verified')) for d in report['documents']),
        'verified_subjects':useful,'coverage_ratio':report['coverage'].get('coverage_ratio'),
        'evidence_ratio':report['coverage'].get('evidence_ratio'),
        'accepted_signals':sum(s.get('validation_status')=='accepted' for s in report['signals']),
        'unresolved_conflicts':sum(c.get('status')=='unresolved' for c in report['conflicts']),
        'tokens':tokens if exact else None,
        'tokens_per_verified_subject':round(tokens/useful,2) if exact and useful else None,
        'duration_ms':sum(int(r.get('duration_ms') or 0) for r in receipts),
        'job_token_limit':request['guardrails']['agent_budget']['job_tokens'],
        'tool_checks':len(checks),'tool_supported':sum(c['status']=='supported' for c in checks),
        'tool_rejections':dict(__import__('collections').Counter(reason for c in checks for reason in c.get('reasons',[]))),
        'context_receipts':len(contexts),'operational_import':False}


def compare(root, baseline_id, candidate_id):
    baseline=summarize(root,baseline_id); candidate=summarize(root,candidate_id)
    checks={
        'same_manifest':baseline['manifest_sha256']==candidate['manifest_sha256'],
        'same_scope':baseline['scope_policy']==candidate['scope_policy'],
        'same_quality_policy':baseline['quality_policy']==candidate['quality_policy'],
        'candidate_within_budget':candidate['tokens'] is not None and candidate['tokens']<=candidate['job_token_limit'],
        'material_coverage_gain':candidate['verified_subjects']>=baseline['verified_subjects']+2,
        'no_conflict_regression':candidate['unresolved_conflicts']<=baseline['unresolved_conflicts'],
        'tool_used':candidate['tool_checks']>0,
        'verified_evidence_present':candidate['verified_documents']>0,
    }
    return {'schema':'mova-agent-comparison-v1','baseline':baseline,'candidate':candidate,
        'checks':checks,'eligible_for_promotion_review':all(checks.values()),
        'autonomy_gate_satisfied':False,
        'limitations':['Sequential live fetches are not a frozen-web randomized benchmark.',
                       'Deterministic identity/topic checks do not establish full claim semantics.',
                       'No experimental result contributes to operational multi-GW acceptance.']}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('baseline');p.add_argument('candidate')
    args=p.parse_args();print(json.dumps(compare(args.root,args.baseline,args.candidate),indent=2))
