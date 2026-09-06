"""Trace cumulative discrepancies through raw history without repairing snapshots."""
from __future__ import annotations

import argparse
from collections import Counter
import gzip
import json
from pathlib import Path

import pandas as pd

from experiments.data_ground_truth.bootstrap_audit import decode, inspect
from experiments.data_ground_truth.bootstrap_performance import cell
from experiments.data_ground_truth.preseason_performance import totals
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked, verify


def assess(element, frame, fields, nominal_time, code):
    if element is None:
        return dict(status='absent_element')
    if element['code'] != code or element['element_type'] not in (1, 2, 3, 4):
        return dict(status='identity_or_entity_mismatch')
    times = pd.to_datetime(frame['event_time_utc'], utc=True, errors='raise')
    if times.isna().any():
        return dict(status='unknown_event_time')
    clock = pd.Timestamp(nominal_time)
    if clock.tzinfo is not None:
        raise ValueError('expected unzoned source clock')
    clock = clock.tz_localize('UTC')  # Hypothesis for diagnostics, never available_at.
    refs = totals(frame.loc[times < clock])
    ref = refs.get(code)
    if ref is None or ref['status'] != 'unique_source_code':
        return dict(status='no_unique_reference')
    cells = {}
    for field in fields:
        observed = cell(element, field)
        final = ref['values'][field]
        cells[field] = dict(observed=observed, final_total=final,
                            residual=observed['value']-final if observed['status']=='valid' and final is not None else None)
    near = bool(((times < clock) & (times >= clock-pd.Timedelta(hours=4))).any())
    residuals = [c['residual'] for c in cells.values()]
    status = 'unknown_component' if None in residuals else ('equal' if all(x==0 for x in residuals) else 'different')
    return dict(status=status, kickoff_within_four_hours=near, cells=cells)


def build(base, package, out):
    raw = base/'raw-bootstrap-snapshots'
    manifest_bytes = (raw/'manifest.json').read_bytes(); manifest = json.loads(manifest_bytes)
    audit_root = base/'bootstrap-audit-v1'
    audit_bytes = (audit_root/'report.json').read_bytes(); audit = json.loads(audit_bytes)
    if audit['manifest_sha256'] != digest(manifest_bytes) or audit['errors'] or manifest['errors']:
        raise ValueError('raw audit binding invalid')
    inventory = json.loads(checked(audit_root/'snapshot_audit.json', audit['artifacts']['snapshot_audit.json']))
    records = {r['path']: r for r in manifest['records']}
    rec_root = base/'cumulative-period-v1'
    rec_bytes = (rec_root/'report.json').read_bytes(); rec = json.loads(rec_bytes)
    reference = verify(package)
    if reference['dataset_id'] != rec['dataset_id']:
        raise ValueError('reference dataset mismatch')
    rows = [json.loads(line) for line in gzip.decompress(checked(rec_root/'comparisons.jsonl.gz',rec['comparisons_sha256'])).splitlines()]
    targets = {}
    for row in rows:
        comparison = row['comparisons']['kickoff_before_deadline']
        if comparison['status'] != 'different':
            continue
        key = (row['season'], row['element'], row['source_code'])
        targets.setdefault(key, []).append(row)
    partitions = {p['season']: p for p in reference['partitions']}
    output, summaries = [], []
    for (season, element_id, code), exceptions in sorted(targets.items()):
        fields = sorted({f for r in exceptions for f in r['comparisons']['kickoff_before_deadline']['differences']})
        start = min(pd.Timestamp(r['deadline']) for r in exceptions)-pd.Timedelta(days=14)
        end = max(pd.Timestamp(r['deadline']) for r in exceptions)+pd.Timedelta(days=30)
        frame = pd.read_csv(package/partitions[season]['file'])
        frame = frame.loc[frame['official_player_code']==code]
        observations = []
        for item in sorted(inventory, key=lambda r:(r['source_claimed_at'],r['path'])):
            clock = pd.Timestamp(item['source_claimed_at']).tz_localize('UTC')
            if item['season'] != season or not start <= clock <= end:
                continue
            record = records[item['path']]
            if record['sha256'] != item['sha256']:
                raise ValueError('inventory object mismatch')
            payload = checked(raw/'objects'/item['sha256'], item['sha256'])
            if len(payload) != record['bytes']:
                raise ValueError('raw size mismatch')
            snapshot = decode(payload); actual, _ = inspect(snapshot, item['path'])
            if actual['season'] != season or actual['source_claimed_at'] != item['source_claimed_at']:
                raise ValueError('snapshot context mismatch')
            element = next((e for e in snapshot['elements'] if e['id']==element_id), None)
            observations.append(dict(source_path=item['path'],source_sha256=item['sha256'],
                                     source_claimed_at=item['source_claimed_at'],available_at=None,
                                     **assess(element,frame,fields,item['source_claimed_at'],code)))
        if not {r['source_sha256'] for r in exceptions} <= {r['source_sha256'] for r in observations}:
            raise ValueError('exception snapshots missing from trace')
        transitions = []
        for before, after in zip(observations, observations[1:]):
            a = {f:c['residual'] for f,c in before.get('cells',{}).items()}
            b = {f:c['residual'] for f,c in after.get('cells',{}).items()}
            if before['status'] != after['status'] or a != b:
                transitions.append(dict(before_sha256=before['source_sha256'],after_sha256=after['source_sha256'],
                                        before_claimed_at=before['source_claimed_at'],after_claimed_at=after['source_claimed_at'],
                                        before_residuals=a,after_residuals=b,
                                        near_kickoff=before.get('kickoff_within_four_hours',False) or after.get('kickoff_within_four_hours',False)))
        context = dict(season=season,element=element_id,source_code=code,fields=fields,
                       nominal_window_start=start.isoformat(),nominal_window_end=end.isoformat())
        output.append(dict(**context,observations=observations))
        summaries.append(dict(**context,observations=len(observations),
                              statuses=dict(Counter(r['status'] for r in observations)),transitions=transitions))
    out.mkdir(parents=True,exist_ok=True)
    payload=(json.dumps(output,indent=2)+'\n').encode();(out/'timelines.json').write_bytes(payload)
    report=dict(version='correction-history-v1',source_manifest_sha256=digest(manifest_bytes),
                source_audit_sha256=digest(audit_bytes),reconciliation_report_sha256=digest(rec_bytes),
                dataset_id=reference['dataset_id'],implementation_sha256=digest(Path(__file__).read_bytes()),
                targets=len(targets),summaries=summaries,timelines_sha256=digest(payload),
                training_admitted=False,production_changed=False,
                limitations=['source_clock_UTC_hypothesis_not_publication_or_capture_proof',
                             'four_hour_flag_does_not_prove_settlement',
                             'final_labels_are_retrospective_reference',
                             'transition_between_captures_not_exact_correction_time',
                             'bounded_window_not_complete_season_trace'])
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('base-root','package','out'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.base_root,a.package,a.out),indent=2))


if __name__=='__main__':main()
