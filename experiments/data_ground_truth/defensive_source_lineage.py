"""Trace missing provider cells across archived revisions; never repair from GT."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import gzip
import io
import json
from pathlib import Path

from experiments.data_ground_truth.bootstrap_performance import cell
from experiments.data_ground_truth.preseason_supplemental import code_key
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked


def observed(row, field):
    if row is None:
        return dict(status='absent_row', value=None)
    if row.get(field) == '':
        return dict(status='empty', value=None)
    return cell(row, field)


def relationship(previous, current):
    if previous['status'] == 'valid' and current is not None:
        return 'equal' if previous['value'] == current else 'different'
    return previous['status'] + ('_to_unknown' if current is None else '_to_observed')


def build(calibration_root, history_root, supplemental_root, raw_root, discovery_root, out):
    parent_bytes = (calibration_root / 'report.json').read_bytes(); parent = json.loads(parent_bytes)
    for name, sha in parent['artifacts'].items():
        checked(calibration_root / name, sha)
    current = [json.loads(x) for x in gzip.decompress((calibration_root/'comparisons.jsonl.gz').read_bytes()).splitlines()]
    history_bytes = (history_root/'manifest.json').read_bytes(); manifest = json.loads(history_bytes)
    expected = {(cut,path) for cut,paths in manifest['scope'].items() for path in paths}
    actual = [(r['cut'],r['path']) for r in manifest['records']]
    if manifest['errors'] or len(actual)!=len(expected) or set(actual)!=expected:
        raise ValueError('incomplete or duplicate history matrix')
    indexes = defaultdict(dict)
    for record in manifest['records']:
        body = checked(history_root/'objects'/record['sha256'],record['sha256'])
        if len(body)!=record['bytes'] or record['revision']!=manifest['cuts'][record['cut']]:
            raise ValueError('history source binding mismatch')
        for number,row in enumerate(csv.DictReader(io.StringIO(body.decode())),start=2):
            key = (row['match_id'],code_key(row['player_id']))
            if key in indexes[record['cut']]:
                raise ValueError('ambiguous historical row')
            indexes[record['cut']][key] = dict(row=row,source_sha256=record['sha256'],path=record['path'],csv_row=number)
    blocks = []; native = []; block_counts = {cut:Counter() for cut in manifest['cuts']}
    native_counts = {cut:Counter() for cut in ('after_july22_backfill','after_july27')}
    recovered = set()
    for row in current:
        key = (row['source_match_id'],code_key(row['player_id']))
        context = dict(source_match_id=key[0],player_id=row['player_id'],fixture=row['fixture'],source_code=row['source_code'])
        if row['provider_actions']['blocks'] is None:
            versions = {}
            for cut in manifest['cuts']:
                entry = indexes[cut].get(key)
                value = observed(entry['row'] if entry else None,'blocks')
                block_counts[cut][value['status']]+=1
                versions[cut] = dict(**value,source=({k:v for k,v in entry.items() if k!='row'} if entry else None))
                if value['status']=='valid':recovered.add(key)
            blocks.append(dict(**context,versions=versions))
        versions = {}
        for cut in native_counts:
            entry = indexes[cut].get(key)
            value = observed(entry['row'] if entry else None,'defensive_contributions')
            kind = relationship(value,row['provider_native_contribution'])
            native_counts[cut][kind]+=1
            versions[cut] = dict(**value,relationship_to_current=kind,
                source=({k:v for k,v in entry.items() if k!='row'} if entry else None))
        native.append(dict(**context,current_value=row['provider_native_contribution'],versions=versions))
    # Separate internal FPL consistency from the provider comparison.
    source_bytes = (supplemental_root/'report.json').read_bytes(); source = json.loads(source_bytes)
    if source['dataset_id']!=parent['dataset_id']:
        raise ValueError('different GT versions')
    payload = checked(supplemental_root/'components.jsonl.gz',source['artifacts']['components.jsonl.gz'])
    raw_manifest = json.loads((raw_root/'manifest.json').read_text())
    recs = [r for r in raw_manifest['records'] if r['repository']=='vaastav/Fantasy-Premier-League' and r['path']=='data/2025-26/players_raw.csv']
    if len(recs)!=1:raise ValueError('ambiguous FPL metadata')
    meta = list(csv.DictReader(io.StringIO(checked(raw_root/'objects'/recs[0]['sha256'],recs[0]['sha256']).decode())))
    identities = {code_key(r['id']):(code_key(r['code']),int(r['element_type'])) for r in meta}
    if len(identities)!=len(meta):raise ValueError('duplicate FPL identity')
    positive_keys = {(r['fixture'],r['source_code']) for r in current if r['FPL_minutes'] and r['position'] in (2,3,4)}
    self_counts = Counter(); positive_counts = Counter(); differences = []
    for line in gzip.decompress(payload).splitlines():
        row = json.loads(line)
        if row['season']!='2025-26':continue
        identity = identities.get(code_key(row['element']))
        if identity is None or identity[0]!=code_key(row['official_player_code']):
            raise ValueError('FPL identity mismatch')
        if identity[1] not in (2,3,4):continue
        names = ['clearances_blocks_interceptions','tackles']+(['recoveries'] if identity[1] in (3,4) else [])
        cells = row['cells']
        if any(cells[f]['status']!='valid' for f in names+['defensive_contribution']):
            status='unknown'
        else:
            status='equal' if sum(cells[f]['value'] for f in names)==cells['defensive_contribution']['value'] else 'different'
        self_counts[status]+=1
        if (row['fixture'],code_key(row['official_player_code'])) in positive_keys:positive_counts[status]+=1
        if status!='equal':differences.append(dict(element=row['element'],fixture=row['fixture'],status=status))
    discovery_bytes = (discovery_root/'manifest.json').read_bytes(); discovery = json.loads(discovery_bytes)
    for record in discovery['records']:checked(discovery_root/'objects'/record['sha256'],record['sha256'])
    out.mkdir(parents=True,exist_ok=True)
    (out/'blocks-lineage.json').write_text(json.dumps(blocks,indent=2)+'\n')
    native_bytes = gzip.compress(('\n'.join(json.dumps(r,sort_keys=True) for r in native)+'\n').encode(),mtime=0)
    (out/'native-lineage.jsonl.gz').write_bytes(native_bytes)
    (out/'FPL-inconsistencies.json').write_text(json.dumps(differences,indent=2)+'\n')
    result = dict(version='defensive-source-lineage-v1',calibration_report_sha256=digest(parent_bytes),
        history_manifest_sha256=digest(history_bytes),discovery_manifest_sha256=digest(discovery_bytes),
        supplemental_report_sha256=digest(source_bytes),FPL_metadata_sha256=recs[0]['sha256'],
        implementation_sha256=digest(Path(__file__).read_bytes()),history_files=len(actual),
        missing_blocks=len(blocks),earlier_observed_blocks_candidates=len(recovered),
        blocks_by_cut={c:dict(v) for c,v in block_counts.items()},
        native_relationships={c:dict(v) for c,v in native_counts.items()},
        FPL_self_consistency=dict(self_counts),FPL_played_outfield_self_consistency=dict(positive_counts),
        upstream_PR='https://github.com/olbauday/FPL-Core-Insights/pull/58',
        upstream_claim='GW FPL totals copied; double-GW values allocated proportionally, 360 rows claimed',
        training_admitted=False,production_changed=False,
        artifacts={n:digest((out/n).read_bytes()) for n in ['blocks-lineage.json','native-lineage.jsonl.gz','FPL-inconsistencies.json']},
        limitations=['upstream_PR_describes_a_historical_patch_not_proof_for_every_current_cell',
                     'sampled_revisions_do_not_exhaust_all_historical_versions',
                     'absence_in_prior_cut_not_proof_of_exact_creation_time_or_cause',
                     'no_zero_imputation_or_label_repair',
                     'documented_proportional_allocation_is_not_observed_per_match_ground_truth',
                     'internal_FPL_consistency_not_independent_measurement_accuracy'])
    (out/'report.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('calibration-root','history-root','supplemental-root','raw-root','discovery-root','out'):
        parser.add_argument('--'+name,type=Path,required=True)
    a=parser.parse_args();print(json.dumps(build(a.calibration_root,a.history_root,a.supplemental_root,a.raw_root,a.discovery_root,a.out),indent=2))


if __name__=='__main__':main()
