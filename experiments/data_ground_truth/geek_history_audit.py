"""Decode public historical player arrays by their declared column mapping."""
from __future__ import annotations
import argparse
from collections import Counter
import csv
import json
from pathlib import Path
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked

FIELDS=('id','code','first_name','second_name','team_id','element_type_id','now_cost',
        'minutes','total_points','event_points','status','added','last_season_points')


def decode(payload):
    mapping=payload['elStat']
    indices=list(mapping.values())
    if any(type(i) is not int or i<0 for i in indices) or len(set(indices))!=len(indices):
        raise ValueError('ambiguous source column mapping')
    if any(name not in mapping for name in FIELDS):
        raise ValueError('required player field absent')
    teams={int(k):v for k,v in payload['eiwteams'].items()}
    rows=[];ids=set();codes=set()
    for source in payload['elInfo']:
        if source is None:
            continue
        if not isinstance(source,list) or len(source)<=max(indices):
            raise ValueError('player array shorter than declared mapping')
        row={name:source[mapping[name]] for name in FIELDS}
        for name in ('id','code','team_id','element_type_id','now_cost','minutes','total_points','event_points','last_season_points'):
            if type(row[name]) is not int:
                raise ValueError('invalid source integer')
        if row['id'] in ids or row['code'] in codes:
            raise ValueError('duplicate source identity')
        if row['team_id'] not in teams:
            raise ValueError('unresolved source team')
        ids.add(row['id']);codes.add(row['code'])
        row.update(team_code=teams[row['team_id']]['code'],available_at=None,
            eligible_predeadline=False,final_observation_proven=False)
        rows.append(row)
    return rows


def build(base,out):
    root=base/'geek-history-g108';mb=(root/'manifest.json').read_bytes();manifest=json.loads(mb)
    if manifest['errors']:
        raise ValueError('incomplete source acquisition')
    discovery=base/'historical-discovery-g108';commits=[];history_hashes={}
    for name in ('data-history.json','data-history-2.json'):
        data=(discovery/name).read_bytes();history_hashes[name]=digest(data);commits.extend(json.loads(data))
    rename=json.loads((discovery/'rename.json').read_bytes())
    if not any(f.get('previous_filename')=='app/js/data.json' and f['status']=='renamed' for f in rename['files']):
        raise ValueError('missing rename evidence')
    expected={c['sha'] for c in commits}-{rename['sha']}
    selected=[r for r in manifest['records'] if r['path']=='app/js/data.json']
    if len(selected)!=len(expected) or {r['revision'] for r in selected}!=expected:
        raise ValueError('incomplete or duplicate historical capture')
    metadata={c['sha']:c for c in commits};states=[];inventory=[]
    for record in manifest['records']:
        payload=checked(root/'objects'/record['sha256'],record['sha256'])
        if len(payload)!=record['bytes']:
            raise ValueError('source size mismatch')
        if record['path']!='app/js/data.json':
            continue
        entry=dict(revision=record['revision'],sha256=record['sha256'],bytes=record['bytes'],
            author_date=metadata[record['revision']]['commit']['author']['date'],available_at=None,eligible_predeadline=False)
        if not payload:
            inventory.append(entry|dict(status='empty_file',players=0));continue
        parsed=json.loads(payload)
        if 'elStat' not in parsed or 'elInfo' not in parsed:
            inventory.append(entry|dict(status='no_player_arrays',players=0,source_keys=sorted(parsed)));continue
        rows=decode(parsed)
        inventory.append(entry|dict(status='decoded',players=len(rows),
            source_team_codes=sorted(t['code'] for t in parsed['eiwteams'].values()),
            min_points=min(r['total_points'] for r in rows),max_points=max(r['total_points'] for r in rows),
            status_counts=dict(Counter(r['status'] for r in rows))))
        states.extend(dict(source_revision=record['revision'],source_sha256=record['sha256'],**r) for r in rows)
    out.mkdir(parents=True,exist_ok=True)
    with (out/'player_states.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(states[0]) if states else []);writer.writeheader();writer.writerows(states)
    (out/'snapshots.json').write_text(json.dumps(inventory,indent=2)+'\n')
    report=dict(version='geek-history-audit-v1',implementation_sha256=digest(Path(__file__).read_bytes()),
        manifest_sha256=digest(mb),history_metadata_sha256=history_hashes,
        rename_evidence_sha256=digest((discovery/'rename.json').read_bytes()),
        captured_files=len(manifest['records']),captured_bytes=sum(r['bytes'] for r in manifest['records']),
        snapshots=len(inventory),unique_snapshot_contents=len({r['sha256'] for r in inventory}),
        snapshot_statuses=dict(Counter(r['status'] for r in inventory)),player_states=len(states),
        min_decoded_players=min(r['players'] for r in inventory if r['status']=='decoded'),max_players=max(r['players'] for r in inventory),
        distinct_team_code_sets=len({tuple(r['source_team_codes']) for r in inventory if r['status']=='decoded'}),
        new_complete_label_seasons=0,finalized_labels_admitted=0,training_admitted=False,gt_changed=False,production_changed=False,
        limitations=['default_branch_history_for_one_path','author_date_not_publication_proof',
            'source_added_is_player_metadata_not_snapshot_availability','accumulated_points_not_match_labels',
            'no_season_or_deadline_assignment','manager_selection_and_forecast_fields_not_exported'],
        artifacts={n:digest((out/n).read_bytes()) for n in ('snapshots.json','player_states.csv')})
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.base,a.out),indent=2))
