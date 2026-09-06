"""Acquire pinned complementary fixture histories without conflating provider identities."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib
import json
from pathlib import Path
import re

from experiments.data_ground_truth.bootstrap_time import parse_log
from experiments.data_ground_truth.raw import capture,digest
from experiments.data_ground_truth.training_dataset import checked

SOURCES={
 'core':dict(repository='olbauday/FPL-Core-Insights',revision='ce03f31b4032f3f89a1aa460ddc8a709ddeb56b6',pattern=r'data/2025-2026/By Tournament/Premier League/GW\d+/(?:fixtures|matches)\.csv'),
 'mirror':dict(repository='TopMarxFPL/fpl-mirror',revision='29cec4c2bb3d53ce0675a889b162043d422307fe',pattern=r'data/2025/csv/fixtures\.csv')}


def select(log_bytes,source):
    config=SOURCES[source];versions=[];deleted=[]
    for path,changes in parse_log(log_bytes.decode()).items():
        if not re.fullmatch(config['pattern'],path):continue
        for change in changes:
            if change['status']=='D':deleted.append(dict(path=path,**change));continue
            if change['status'] not in ('A','M') or change['new_blob']=='0'*40:raise ValueError('unsupported complement change')
            versions.append(dict(path=path,**change))
    if not versions:raise ValueError('empty complement selection')
    if len({(r['path'],r['commit']) for r in versions})!=len(versions):raise ValueError('duplicate complement version')
    return sorted(versions,key=lambda r:(r['committer_at'],r['commit'],r['path'])),deleted


def acquire_one(root,config,v):
    r=capture(root,config['repository'],v['commit'],v['path']);data=checked(root/'objects'/r['sha256'],r['sha256'])
    if hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()!=v['new_blob']:raise ValueError('complement Git blob mismatch')
    return dict(r,season='2025-26',committer_at=v['committer_at'],author_at=v['author_at'],git_blob=v['new_blob'],change_status=v['status'])


def build(source:str,log:Path,out:Path):
    config=SOURCES[source];log_bytes=log.read_bytes();versions,deleted=select(log_bytes,source)
    out.mkdir(parents=True,exist_ok=True);records=[];errors=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures={pool.submit(acquire_one,out,config,v):v for v in versions}
        for i,future in enumerate(as_completed(futures),1):
            v=futures[future]
            try:records.append(future.result())
            except Exception as exc:errors.append(dict(path=v['path'],revision=v['commit'],error=type(exc).__name__))
            if i%100==0:print(json.dumps(dict(completed=i,expected=len(versions),errors=len(errors))),flush=True)
    records.sort(key=lambda r:(r['committer_at'],r['revision'],r['path']))
    report=dict(version='fixture-complement-v1',source=source,repository=config['repository'],pinned_revision=config['revision'],
        git_log_sha256=digest(log_bytes),implementation_sha256=digest(Path(__file__).read_bytes()),expected_versions=len(versions),
        records=records,errors=errors,deleted_versions=deleted,distinct_objects=len({r['sha256'] for r in records}),
        bytes=sum(r['bytes'] for r in records),eligible_predeadline=False,production_changed=False,
        limitations=['provider_match_and_team_ids_are_not_automatically_FPL_ids','files_from_different_commits_are_not_a_coherent_calendar'])
    (out/'manifest.json').write_text(json.dumps(report,indent=2)+'\n');return report


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--source',choices=sorted(SOURCES),required=True)
    ap.add_argument('--log',type=Path,required=True);ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args();r=build(a.source,a.log,a.out);print(json.dumps({k:v for k,v in r.items() if k not in ('records','deleted_versions')},indent=2))
    if r['errors']:raise SystemExit(1)


if __name__=='__main__':main()
