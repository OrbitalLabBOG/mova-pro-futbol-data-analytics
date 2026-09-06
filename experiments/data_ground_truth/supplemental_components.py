"""Inventory supplemental match components without admitting future features."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime
from decimal import Decimal
import gzip
import io
import json
from pathlib import Path

from experiments.data_ground_truth.bootstrap_performance import cell
from experiments.data_ground_truth.discovery_2014 import integer
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked, verify

FIELDS = ('starts','expected_goals','expected_assists','expected_goals_conceded',
          'expected_goal_involvements','defensive_contribution','recoveries','tackles',
          'clearances_blocks_interceptions')


def cells(row):
    # CSV empty cells are null; an absent column remains absent.
    normalized = {k: None if v == '' else v for k,v in row.items()}
    result = {field: cell(normalized,field) for field in FIELDS}
    if result['starts']['status']=='valid' and result['starts']['value'] not in (0,1):
        result['starts'] = dict(status='invalid_match_starts',value=None)
    return result


def instant(value):
    if not value:
        return None
    result = datetime.fromisoformat(value.replace('Z','+00:00'))
    if result.tzinfo is None:
        raise ValueError('unqualified match time')
    return result


def linkage(row, reference):
    if reference is None:
        return 'no_player_reference'
    if integer(row['round']) != integer(reference['gw']):
        return 'gameweek_mismatch'
    left, right = instant(row['kickoff_time']), instant(reference['event_time_utc'])
    if left is None or right is None:
        return 'unknown_match_time'
    if left != right:
        return 'kickoff_mismatch'
    return 'linked'


def build(raw_root, package, out):
    source = (raw_root/'manifest.json').read_bytes(); manifest = json.loads(source)
    if manifest['errors'] or len(manifest['records']) != manifest['expected_files']:
        raise ValueError('incomplete raw acquisition')
    verified = verify(package)
    references = {}
    for p in verified['partitions']:
        rows = csv.DictReader(io.StringIO(gzip.decompress(checked(package/p['file'],p['sha256'])).decode()))
        for row in rows:
            key = (p['season'],integer(row['element']),integer(row['fixture']))
            if key in references:
                raise ValueError('duplicate GT key')
            references[key] = row
    # Retain all witnesses. Conflicting duplicate values are not silently selected.
    candidates = {}; files = Counter(); empty_files = Counter()
    for record in manifest['records']:
        season = record['path'].split('/')[1]; files[season] += 1
        data = checked(raw_root/'objects'/record['sha256'],record['sha256'])
        if len(data) != record['bytes']:
            raise ValueError('raw size mismatch')
        reader = csv.DictReader(io.StringIO(data.decode('utf-8-sig')))
        count = 0
        for row in reader:
            if None in row:
                raise ValueError('malformed CSV row')
            count += 1
            key = (season,integer(row['element']),integer(row['fixture']))
            candidates.setdefault(key,[]).append(dict(source_path=record['path'],source_sha256=record['sha256'],
                                                       linkage=linkage(row,references.get(key)),cells=cells(row)))
        if not count:
            empty_files[season] += 1
    coverage = {}; output = []; quarantine = []
    for season in sorted(set(files) | {k[0] for k in references}):
        coverage[season] = dict(files=files[season],empty_files=empty_files[season],
                                reference_rows=sum(k[0]==season for k in references),
                                statuses=Counter(),fields={f:Counter() for f in FIELDS},
                                value_activity={f:Counter() for f in FIELDS})
    for key,witnesses in sorted(candidates.items()):
        season,element,fixture = key
        signatures = {json.dumps(dict(linkage=w['linkage'],cells=w['cells']),sort_keys=True) for w in witnesses}
        status = 'conflicting_witnesses' if len(signatures)>1 else witnesses[0]['linkage']
        coverage[season]['statuses'][status] += 1
        context = dict(season=season,element=element,fixture=fixture,status=status,witnesses=witnesses)
        if status != 'linked':
            quarantine.append(context)
            continue
        values = witnesses[0]['cells']
        for field,value in values.items():
            coverage[season]['fields'][field][value['status']] += 1
            if value['status']=='valid':
                activity='zero' if Decimal(str(value['value']))==0 else 'positive'
                coverage[season]['value_activity'][field][activity] += 1
        ref = references[key]
        output.append(dict(season=season,element=element,fixture=fixture,gw=integer(ref['gw']),
                           official_player_code=ref['official_player_code'],event_time_utc=ref['event_time_utc'],
                           cells=values,sources=[dict(path=w['source_path'],sha256=w['source_sha256']) for w in witnesses],
                           available_at=None,eligible_predeadline=False))
    covered = set(candidates)
    for key in references:
        if key not in covered:
            coverage[key[0]]['statuses']['reference_without_source'] += 1
    out.mkdir(parents=True,exist_ok=True)
    payload = gzip.compress(('\n'.join(json.dumps(r,sort_keys=True) for r in output)+'\n').encode(),mtime=0)
    (out/'components.jsonl.gz').write_bytes(payload)
    rejected = (json.dumps(quarantine,indent=2)+'\n').encode();(out/'quarantine.json').write_bytes(rejected)
    result = dict(version='supplemental-components-v1',source_manifest_sha256=digest(source),
                  dataset_id=verified['dataset_id'],implementation_sha256=digest(Path(__file__).read_bytes()),
                  linked_rows=len(output),quarantined_keys=len(quarantine),coverage=coverage,
                  artifacts={'components.jsonl.gz':digest(payload),'quarantine.json':digest(rejected)},
                  training_admitted=False,production_changed=False,
                  limitations=['retrospective_match_values_not_predeadline_features',
                               'fixture_and_time_match_not_independent_identity_corroboration',
                               'no_cross_source_semantic_confirmation_of_supplemental_values',
                               'absent_columns_and_null_cells_remain_unknown',
                               'nonplayer_or_unmatched_rows_not_admitted'])
    (out/'report.json').write_text(json.dumps(result,indent=2)+'\n');return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('raw-root','package','out'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();r=build(a.raw_root,a.package,a.out);print(json.dumps(dict(linked_rows=r['linked_rows'],quarantined_keys=r['quarantined_keys'])))


if __name__=='__main__':main()
