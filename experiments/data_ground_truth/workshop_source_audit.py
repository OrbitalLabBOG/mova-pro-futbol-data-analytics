"""Audit workshop CSV shape and name-only state candidates without label admission."""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import csv
from decimal import Decimal
import io
import json
from pathlib import Path
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked

REFERENCE='b499ccddd7bcbcb78e9c429e597efe797785ead16054ec6252e07ee368737274'
FIELDS=('total_points','minutes','now_cost','goals_scored','assists','clean_sheets','goals_conceded',
        'own_goals','penalties_saved','penalties_missed','yellow_cards','red_cards','saves','bonus','ea_index','bps')


def read_csv(data):
    try:
        rows=list(csv.reader(io.StringIO(data.decode('utf-8')),strict=True))
    except csv.Error as error:
        return dict(status='invalid_csv',error=str(error)),[]
    if not rows:
        return dict(status='empty'),[]
    header=rows[0];widths=Counter(len(row) for row in rows[1:])
    valid=all(len(row)==len(header) for row in rows[1:]) and len(set(header))==len(header)
    report=dict(status='rectangular' if valid else 'invalid_shape',columns=len(header),
        parsed_records=len(rows)-1,width_counts=dict(sorted(widths.items())),header=header)
    return report,[dict(zip(header,row)) for row in rows[1:]] if valid else []


def candidates(rows,profiles):
    index=defaultdict(list)
    for profile in profiles:
        index[(profile['first_name'],profile['second_name'])].append(profile)
    output=[]
    for row in rows:
        matches=index[(row['first_name'],row['second_name'])]
        entry=dict(first_name=row['first_name'],second_name=row['second_name'],
            status='unique_name_candidate' if len(matches)==1 else ('ambiguous_name' if matches else 'unmatched'),
            verified_identity=False,eligible_training=False,available_at=None)
        if len(matches)==1:
            profile=matches[0]
            entry.update(candidate_id=profile['id'],candidate_code=profile['code'],
                fields={name:dict(source=row[name],reference=profile[name],
                    equal=Decimal(row[name])==Decimal(str(profile[name]))) for name in FIELDS})
        output.append(entry)
    return output


def build(base,out):
    root=base/'workshop-source-g107';manifest=(root/'manifest.json').read_bytes()
    records=json.loads(manifest)['records'];inventory=[];comparisons=[]
    profiles=json.loads(checked(base/'profile-snapshots-g100/objects'/REFERENCE,REFERENCE))
    for record in records:
        payload=checked(root/'objects'/record['sha256'],record['sha256'])
        entry={k:record[k] for k in ('path','sha256','revision','bytes')}
        if record['path'].endswith('.csv'):
            shape,rows=read_csv(payload);entry.update(shape)
            if record['path']=='sessions/w5/data/soccer.csv':
                comparisons=candidates(rows,profiles.values())
        else:
            entry.update(status='context_not_executed')
        inventory.append(entry)
    out.mkdir(parents=True,exist_ok=True)
    for name,value in [('inventory.json',inventory),('candidates.json',comparisons)]:
        (out/name).write_text(json.dumps(value,indent=2)+'\n')
    paired=[r for r in comparisons if r['status']=='unique_name_candidate']
    report=dict(version='workshop-source-audit-v1',implementation_sha256=digest(Path(__file__).read_bytes()),
        manifest_sha256=digest(manifest),reference_sha256=REFERENCE,captured_files=len(records),
        captured_bytes=sum(r['bytes'] for r in records),profiles=len(comparisons),
        candidate_statuses=dict(Counter(r['status'] for r in comparisons)),
        equal_field_counts={name:sum(r['fields'][name]['equal'] for r in paired) for name in FIELDS},
        verified_identities=0,new_complete_seasons=0,finalized_labels_admitted=0,training_admitted=False,
        gt_changed=False,production_changed=False,
        limitations=['full_name_match_only_not_verified_identity','reference_is_one_archived_state_not_final_gt',
            'course_date_not_data_capture_time','no_season_or_gameweek_assigned','malformed_csv_not_repaired',
            'forecast_fields_excluded_from_outcome_comparison'],
        artifacts={n:digest((out/n).read_bytes()) for n in ('inventory.json','candidates.json')})
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.base,a.out),indent=2))
