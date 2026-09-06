"""Acquire pinned player history CSVs separately from gameweek archives."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import json
from pathlib import Path
import re

from experiments.data_ground_truth.raw import capture,digest

REPOSITORY='vaastav/Fantasy-Premier-League'


def acquire(root: Path,inventory: Path,revision: str,snapshot_season: str | None=None,artifact: str="history"):
    raw=inventory.read_bytes();tree=json.loads(raw)
    if tree.get('sha')!=revision or tree.get('truncated',True):raise ValueError('invalid pinned history inventory')
    if snapshot_season is not None and (not re.fullmatch(r'[0-9]{4}-[0-9]{2}',snapshot_season) or (int(snapshot_season[:4])+1)%100!=int(snapshot_season[-2:])):
        raise ValueError('invalid snapshot season')
    if artifact not in {'history','gw'}:raise ValueError('unsupported player artifact')
    pattern=(r'data/'+re.escape(snapshot_season)+r'/players/[^/]+/history\.csv') if snapshot_season else r'data/20(?:1[6-9]|2[0-5])-[0-9]{2}/players/[^/]+/history\.csv'
    if artifact=='gw':pattern=pattern.replace(r'history\.csv',r'gw\.csv')
    paths=sorted(r['path'] for r in tree['tree'] if r.get('type')=='blob' and
        re.fullmatch(pattern,r['path']))
    if not paths:raise ValueError('no player histories in selected snapshot')
    if len(set(paths))!=len(paths):raise ValueError('duplicate history path')
    root.mkdir(parents=True,exist_ok=True);(root/'inventory.json').write_bytes(raw)
    records=[];errors=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures={pool.submit(capture,root,REPOSITORY,revision,p):p for p in paths}
        for i,future in enumerate(as_completed(futures),1):
            try:records.append(future.result())
            except Exception as exc:errors.append(dict(path=futures[future],error=type(exc).__name__))
            if i%250==0:print(json.dumps(dict(completed=i,total=len(paths),errors=len(errors))),flush=True)
    records.sort(key=lambda r:r['path']);errors.sort(key=lambda r:r['path'])
    report=dict(version='player-'+artifact+'-acquisition-v1',repository=REPOSITORY,revision=revision,artifact=artifact,
        inventory_sha256=digest(raw),expected_files=len(paths),records=records,errors=errors)
    if snapshot_season:report['snapshot_season']=snapshot_season
    (root/'manifest.json').write_text(json.dumps(report,indent=2)+'\n');return report


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root',type=Path,required=True);ap.add_argument('--inventory',type=Path,required=True);ap.add_argument('--revision',required=True)
    ap.add_argument('--snapshot-season')
    ap.add_argument('--artifact',choices=['history','gw'],default='history')
    args=ap.parse_args();r=acquire(args.root,args.inventory,args.revision,args.snapshot_season,args.artifact)
    print(json.dumps(dict(files=len(r['records']),errors=r['errors'])),flush=True)
    if r['errors']:raise SystemExit(1)


if __name__=='__main__':main()
