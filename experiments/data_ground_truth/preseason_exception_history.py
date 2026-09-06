"""Trace unresolved preseason statistics through raw snapshots without repairing them."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path

from experiments.data_ground_truth.bootstrap_audit import decode, inspect
from experiments.data_ground_truth.bootstrap_performance import cell
from experiments.data_ground_truth.preseason_performance import FIELDS
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked


def observed(element, expected_code):
    if element is None:
        return dict(status='absent_element', cells={})
    if element['code'] != expected_code or element['element_type'] not in (1, 2, 3, 4):
        return dict(status='identity_or_entity_mismatch', cells={})
    return dict(status='present', cells={f: cell(element, f) for f in FIELDS})


def summarize(rows, reference):
    present = [r for r in rows if r['status'] == 'present']
    matching = [r for r in present if all(r['cells'][f]['status'] == 'valid' and
                r['cells'][f]['value'] == v['prior_total'] for f, v in reference.items())]
    changed = sum(a['status'] != b['status'] or a['cells'] != b['cells'] for a, b in zip(rows, rows[1:]))
    return dict(observations=len(rows), statuses=dict(Counter(r['status'] for r in rows)),
                first_present=present[0]['source_claimed_at'] if present else None,
                last_present=present[-1]['source_claimed_at'] if present else None,
                matches_prior_totals=len(matching), first_match=matching[0]['source_claimed_at'] if matching else None,
                state_transitions=changed)


def build(raw_root: Path, audit_root: Path, reconciliation_root: Path, out: Path):
    manifest_bytes = (raw_root/'manifest.json').read_bytes(); manifest = json.loads(manifest_bytes)
    audit_bytes = (audit_root/'report.json').read_bytes(); audit = json.loads(audit_bytes)
    if audit['manifest_sha256'] != digest(manifest_bytes) or audit['errors'] or manifest['errors']:
        raise ValueError('source audit binding invalid')
    records = {r['path']:r for r in manifest['records']}
    inventory = json.loads(checked(audit_root/'snapshot_audit.json', audit['artifacts']['snapshot_audit.json']))
    rec_bytes = (reconciliation_root/'report.json').read_bytes(); rec = json.loads(rec_bytes)
    comparisons = json.loads(checked(reconciliation_root/'comparisons.json', rec['comparisons_sha256']))
    targets = [r for r in comparisons if r['status'] == 'different']
    timelines = {(r['season'], r['element']): [] for r in targets}; scanned = set()
    for s in sorted(inventory, key=lambda r:r['source_claimed_at']):
        clock = datetime.fromisoformat(s['source_claimed_at']).replace(tzinfo=timezone.utc)
        active = [t for t in targets if t['season'] == s['season'] and clock < datetime.fromisoformat(t['deadline'].replace('Z','+00:00'))]
        if not active:
            continue
        record = records[s['path']]
        if record['sha256'] != s['sha256']:
            raise ValueError('inventory raw mismatch')
        snapshot = decode(checked(raw_root/'objects'/s['sha256'],s['sha256']))
        actual, _ = inspect(snapshot, s['path'])
        if actual['season'] != s['season'] or actual['source_claimed_at'] != s['source_claimed_at']:
            raise ValueError('inventory season or clock mismatch')
        elements = {e['id']:e for e in snapshot['elements']}; scanned.add(s['path'])
        for target in active:
            timelines[(target['season'],target['element'])].append(dict(source_path=s['path'], source_sha256=s['sha256'],
                source_claimed_at=s['source_claimed_at'], **observed(elements.get(target['element']),target['source_code'])))
    summaries=[]; output=[]
    for t in targets:
        rows=timelines[(t['season'],t['element'])]
        if not any(r['source_sha256']==t['source_sha256'] for r in rows):
            raise ValueError('selected exception snapshot missing from history')
        context=dict(season=t['season'],element=t['element'],source_code=t['source_code'],deadline=t['deadline'],selected_source_sha256=t['source_sha256'])
        summaries.append(dict(**context,**summarize(rows,t['fields'])))
        output.append(dict(**context,observations=rows))
    out.mkdir(parents=True,exist_ok=True)
    payload=(json.dumps(output,indent=2)+'\n').encode();(out/'timelines.json').write_bytes(payload)
    report=dict(version='preseason-exception-history-v1',source_manifest_sha256=digest(manifest_bytes),
                source_audit_sha256=digest(audit_bytes),reconciliation_report_sha256=digest(rec_bytes),
                implementation_sha256=digest(Path(__file__).read_bytes()),scanned_snapshots=len(scanned),
                targets=len(targets),summaries=summaries,timelines_sha256=digest(payload),
                production_changed=False,training_admitted=False,
                limitations=['source_claimed_clock_not_publication_proof','absence_between_captures_not_continuous_absence',
                             'earlier_matches_do_not_authorize_replacing_selected_values'])
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('raw-root','audit-root','reconciliation-root','out'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();r=build(a.raw_root,a.audit_root,a.reconciliation_root,a.out)
    print(json.dumps(r,indent=2))


if __name__=='__main__':main()
