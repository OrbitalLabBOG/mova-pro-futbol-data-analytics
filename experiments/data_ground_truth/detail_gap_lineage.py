"""Trace missing match-detail keys without inventing identity or zero observations."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import gzip
import io
import json
from pathlib import Path

from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked


def inspect_key(rows, player):
    exact = [(number, row) for number, row in rows if row.get('player_id') == player]
    unknown = sum(not row.get('player_id') for _, row in rows)
    if len(exact) > 1:
        return dict(status='ambiguous_exact_key', matches=exact, unidentified_rows=unknown)
    if exact:
        return dict(status='exact_key_present', matches=exact, unidentified_rows=unknown)
    return dict(status='absent_exact_key', matches=[], unidentified_rows=unknown)


def build(details_root, calibration_root, history_root, out):
    detail_bytes = (details_root/'report.json').read_bytes(); detail = json.loads(detail_bytes)
    issue_bytes = checked(details_root/'coverage-issues.json',detail['artifacts']['coverage-issues.json'])
    issues = [r for r in json.loads(issue_bytes) if r['table'] in ('average_positions','player_match_enrichment')]
    raw = checked(details_root/'observations.jsonl.gz',detail['artifacts']['observations.jsonl.gz'])
    observations = [json.loads(line) for line in gzip.decompress(raw).splitlines()]
    lookup = {(r['table'],r['raw']['match_id']):r['path'] for r in observations}
    targets = sorted({lookup[(r['table'],r['match_id'])] for r in issues})
    cuts = {'initial':'4f12bc1069f59137fcb03e34ab8bcf60502f1b22',
            'integrated':'b18f816fbaa21db5b55f9c4af117da4d0f8f11c1',
            'current_gameweek':'ce03f31b4032f3f89a1aa460ddc8a709ddeb56b6'}
    expected = {(cut,revision,path if cut!='current_gameweek' else path.replace('By Tournament/Premier League','By Gameweek'))
                for path in targets for cut,revision in cuts.items()}
    evidence_paths = ('data/2025-2026/supplemental/incidents_quarantined.csv','DATA_INTEGRATION_REVIEW.md')
    expected |= {('evidence',cuts['current_gameweek'],path) for path in evidence_paths}
    manifest_bytes = (history_root/'manifest.json').read_bytes(); manifest = json.loads(manifest_bytes)
    actual = [(r['cut'],r['revision'],r['path']) for r in manifest['records']]
    if manifest['errors'] or len(actual)!=len(expected) or set(actual)!=expected:
        raise ValueError('incomplete or duplicate historical scope')
    indexes = {}; sources = {}; evidence = {}; total_bytes = 0
    for record in manifest['records']:
        if record['repository']!='olbauday/FPL-Core-Insights':raise ValueError('unexpected source')
        body = checked(history_root/'objects'/record['sha256'],record['sha256'])
        if len(body)!=record['bytes']:raise ValueError('source size mismatch')
        total_bytes += len(body)
        if record['cut']=='evidence': evidence[record['path']] = body; continue
        groups = defaultdict(list)
        for number,row in enumerate(csv.DictReader(io.StringIO(body.decode())),start=2):
            groups[row['match_id']].append((number,row))
        key = (record['cut'],record['path']); indexes[key]=groups; sources[key]=record['sha256']
    parent_bytes = (calibration_root/'report.json').read_bytes(); parent = json.loads(parent_bytes)
    if parent['dataset_id']!=detail['dataset_id']:raise ValueError('different GT versions')
    data = checked(calibration_root/'comparisons.jsonl.gz',parent['artifacts']['comparisons.jsonl.gz'])
    comparisons = [json.loads(line) for line in gzip.decompress(data).splitlines()]
    reference = {(r['source_match_id'],str(r['player_id'])):r for r in comparisons}
    output=[]; counts=defaultdict(Counter); minutes=defaultdict(Counter); gameweeks=defaultdict(Counter)
    for issue in issues:
        path = lookup[(issue['table'],issue['match_id'])]; versions={}
        ref = reference[(issue['match_id'],issue['player_id'])]
        minutes[issue['table']][ref['FPL_minutes']]+=1; gameweeks[issue['table']][ref['FPL_gw']]+=1
        for cut in cuts:
            source_path = path if cut!='current_gameweek' else path.replace('By Tournament/Premier League','By Gameweek')
            key=(cut,source_path); assessment=inspect_key(indexes[key].get(issue['match_id'],[]),issue['player_id'])
            counts[issue['table']+':'+cut][assessment['status']]+=1
            versions[cut]=dict(**assessment,source_sha256=sources[key],path=source_path)
        output.append(dict(**issue,fixture=ref['fixture'],player_code=ref['source_code'],
            FPL_minutes=ref['FPL_minutes'],FPL_gw=ref['FPL_gw'],versions=versions,training_admitted=False))
    quarantine = list(csv.DictReader(io.StringIO(evidence[evidence_paths[0]].decode())))
    canonical = [r['raw'] for r in observations if r['table']=='incidents']
    matches={r['source_match_id'] for r in comparisons}
    def negative(row):return row.get('minute') not in ('',None) and float(row['minute'])<0
    def unknown(row):return row.get('player_name')=='Unknown'
    quarantine_report=dict(rows=len(quarantine),negative_minute=sum(map(negative,quarantine)),
        unknown_actor=sum(map(unknown,quarantine)),missing_player_id=sum(not r['player_id'] for r in quarantine),
        reasons=dict(Counter(r['quarantine_reason'] for r in quarantine)),
        matches=len({r['match_id'] for r in quarantine}),outside_reference_matches=sorted({r['match_id'] for r in quarantine}-matches),
        canonical_rows=len(canonical),canonical_negative_minute=sum(map(negative,canonical)),
        canonical_unknown_actor=sum(map(unknown,canonical)))
    out.mkdir(parents=True,exist_ok=True)
    (out/'gap-lineage.json').write_text(json.dumps(output,indent=2)+'\n')
    # Preserve excluded bytes, separate from canonical incidents and training inputs.
    (out/'incidents-quarantined.csv').write_bytes(evidence[evidence_paths[0]])
    result = dict(version='detail-gap-lineage-v1',dataset_id=detail['dataset_id'],
        detail_report_sha256=digest(detail_bytes),calibration_report_sha256=digest(parent_bytes),
        history_manifest_sha256=digest(manifest_bytes),implementation_sha256=digest(Path(__file__).read_bytes()),
        review_document_sha256=digest(evidence[evidence_paths[1]]),source_files=len(actual),source_bytes=total_bytes,
        gaps=len(issues),lineage_counts={k:dict(v) for k,v in counts.items()},
        gap_minutes={k:dict(sorted(v.items())) for k,v in minutes.items()},gap_gameweeks={k:dict(sorted(v.items())) for k,v in gameweeks.items()},
        quarantine=quarantine_report,
        upstream_claim='31 enrichment rows excluded as placeholder statistics; number agreement is not individual raw-stream verification',
        training_admitted=False,new_FPL_labels=0,production_changed=False,
        limitations=['absent_exact_key_does_not_exclude_unidentified_row',
            'earlier_present_row_not_automatically_valid_or_recoverable',
            'same_provider_projections_not_independent_evidence',
            'upstream_private_raw_stream_not_available_in_inspected_repository',
            'no_fuzzy_identity_match_zero_imputation_or_label_repair'],
        artifacts={n:digest((out/n).read_bytes()) for n in ('gap-lineage.json','incidents-quarantined.csv')})
    (out/'report.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('details-root','calibration-root','history-root','out'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.details_root,a.calibration_root,a.history_root,a.out),indent=2))


if __name__=='__main__':main()
