"""Acquire a pinned snapshot tree and inventory content without temporal admission."""
from __future__ import annotations
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
from experiments.data_ground_truth.raw import capture,digest
from experiments.data_ground_truth.training_dataset import checked

REPO='llimllib/fantasypl_stats'
PIN='db590f1925289069d171dc9766928cdd14817833'
TREE_SHA='094c125f4c970a04120f55a51015f484d302449f3fa512b92fd4cb06b64401ef'


def inventory(tree):
    if tree.get('sha')!=PIN or tree.get('truncated'):raise ValueError('incomplete or wrong tree')
    files=[r for r in tree['tree'] if r['type']=='blob' and re.fullmatch(r'data/players\.[0-9]+\.json',r['path'])]
    if not files or len({r['path'] for r in files})!=len(files):raise ValueError('empty or duplicate inventory')
    return sorted(files,key=lambda r:r['path'])


def verify_blob(data,entry):
    if len(data)!=entry['size'] or hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()!=entry['sha']:
        raise ValueError('Git tree blob mismatch')


def acquire(base):
    treepath=base/'historical-discovery-g98/llimllib--fantasypl_stats.json'
    files=inventory(json.loads(checked(treepath,TREE_SHA)));root=base/'profile-snapshots-g100';root.mkdir(exist_ok=True)
    def one(entry):
        try:
            record=capture(root,REPO,PIN,entry['path'])
            verify_blob(checked(root/'objects'/record['sha256'],record['sha256']),entry)
            return record,None
        except Exception as error:return None,dict(path=entry['path'],error=type(error).__name__,detail=str(error))
    records=[];errors=[]
    with ThreadPoolExecutor(8) as pool:
        for i,(r,e) in enumerate(pool.map(one,files),1):
            (errors if e else records).append(e or r)
            if i%100==0:print(f'acquired {i}/{len(files)} errors={len(errors)}',flush=True)
    manifest=dict(repository=REPO,revision=PIN,tree_sha256=TREE_SHA,expected_files=len(files),records=records,errors=errors)
    (root/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    if errors:raise ValueError(f'{len(errors)} failed captures; receipts retained for resume')
    return manifest


def describe(players):
    if not isinstance(players,dict):return dict(status='unsupported_container',profiles=None)
    if not players:return dict(status='empty',profiles=0,history_rows=0)
    if any(not isinstance(p,dict) or str(p.get('id'))!=key for key,p in players.items()):
        return dict(status='profile_id_mismatch',profiles=len(players))
    histories=[];annual=set();weeks=set();rows=0;codes=[]
    for key,p in sorted(players.items(),key=lambda item:int(item[0])):
        history=p.get('fixture_history')
        if not isinstance(history,dict) or not isinstance(history.get('all'),list):return dict(status='unsupported_history',profiles=len(players))
        values=history['all']
        if any(not isinstance(r,list) or len(r)!=20 for r in values):return dict(status='unsupported_row_schema',profiles=len(players))
        for r in values:weeks.add(r[1])
        annual.update(r[0] for r in p.get('season_history',[]) if isinstance(r,list) and r)
        rows+=len(values);codes.append(p.get('code'));histories.append([int(key),values])
    return dict(status='profile_history_schema_valid',profiles=len(players),history_rows=rows,gameweeks=sorted(weeks),
        annual_seasons=sorted(annual),duplicate_or_missing_codes=len(codes)-len(set(codes))+sum(c is None for c in codes),
        history_sha256=digest(json.dumps(histories,sort_keys=True,separators=(',',':')).encode()),
        observed_labels_normalized=False,publication_proven=False)


def describe_payload(data):
    try:
        players=json.loads(data)
    except (json.JSONDecodeError,UnicodeDecodeError) as error:
        return dict(status='invalid_json',profiles=None,error_type=type(error).__name__,error_offset=getattr(error,'pos',None))
    return describe(players)


def audit(base,out):
    root=base/'profile-snapshots-g100';raw=(root/'manifest.json').read_bytes();manifest=json.loads(raw)
    files=inventory(json.loads(checked(base/'historical-discovery-g98/llimllib--fantasypl_stats.json',TREE_SHA)))
    records=manifest['records'];expected={e['path']:e for e in files}
    if manifest['errors'] or len(records)!=len(files) or {r['path'] for r in records}!=set(expected):raise ValueError('incomplete capture')
    entries=[];out.mkdir(parents=True,exist_ok=True)
    for i,r in enumerate(records,1):
        if r['repository']!=REPO or r['revision']!=PIN:raise ValueError('source pin mismatch')
        data=checked(root/'objects'/r['sha256'],r['sha256']);verify_blob(data,expected[r['path']])
        quality=describe_payload(data);timestamp=int(r['path'].split('.')[1]);nominal=datetime.fromtimestamp(timestamp,timezone.utc).isoformat()
        entries.append(dict(path=r['path'],sha256=r['sha256'],bytes=len(data),nominal_filename_time=nominal,
            available_at=None,eligible_predeadline=False,**quality))
        if i%200==0:print(f'audited {i}/{len(records)}',flush=True)
    (out/'snapshots.json').write_text(json.dumps(entries,indent=2)+'\n')
    report=dict(version='profile-snapshot-collection-v1',manifest_sha256=digest(raw),tree_sha256=TREE_SHA,
        implementation_sha256=digest(Path(__file__).read_bytes()),files=len(entries),bytes=sum(e['bytes'] for e in entries),
        unique_contents=len({e['sha256'] for e in entries}),statuses=dict(Counter(e['status'] for e in entries)),
        unique_history_projections=len({e['history_sha256'] for e in entries if 'history_sha256' in e}),
        nominal_months=dict(sorted(Counter(e['nominal_filename_time'][:7] for e in entries).items())),
        new_complete_seasons=0,training_admitted=False,production_changed=False,
        artifacts={'snapshots.json':digest((out/'snapshots.json').read_bytes())},
        limitations=['filename_time_not_publication_proof','schema_validation_not_fixture_reconciliation',
                    'history_projection_excludes_mutable_profile_state','raw_forecasts_not_observed_labels',
                    'snapshot_rows_must_not_be_summed_as_unique_observations'])
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base',type=Path,required=True);p.add_argument('--out',type=Path);p.add_argument('--acquire',action='store_true')
    a=p.parse_args()
    if a.acquire:acquire(a.base)
    if a.out:print(json.dumps(audit(a.base,a.out),indent=2))
