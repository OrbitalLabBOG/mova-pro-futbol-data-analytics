"""Acquire every fixture CSV version in a pinned Git history, preserving publication uncertainty."""
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

REPOSITORY='vaastav/Fantasy-Premier-League'
REVISION='9779cdbc0c07f6c900c2d0c181ddf6bb9c800f88'


def inventory(log_bytes):
    history=parse_log(log_bytes.decode());versions=[];excluded=[]
    for path,changes in sorted(history.items()):
        if not re.fullmatch(r'data/20\d{2}-\d{2}/fixtures\.csv',path):raise ValueError('unexpected fixture path')
        for change in changes:
            if change['status']=='D':excluded.append(dict(path=path,**change));continue
            if change['status'] not in ('A','M') or change['new_blob']=='0'*40:raise ValueError('unsupported fixture change')
            versions.append(dict(path=path,season=path.split('/')[1],**change))
    keys={(r['path'],r['commit']) for r in versions}
    if len(keys)!=len(versions):raise ValueError('duplicate fixture version')
    return sorted(versions,key=lambda r:(r['season'],r['committer_at'],r['commit'])),excluded


def acquire_one(root,version):
    record=capture(root,REPOSITORY,version['commit'],version['path'])
    data=checked(root/'objects'/record['sha256'],record['sha256'])
    blob=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
    if blob!=version['new_blob']:raise ValueError('fixture Git blob mismatch')
    return dict(record,season=version['season'],git_blob=blob,committer_at=version['committer_at'],author_at=version['author_at'],change_status=version['status'])


def build(log:Path,out:Path):
    log_bytes=log.read_bytes();versions,excluded=inventory(log_bytes)
    out.mkdir(parents=True,exist_ok=True)
    records,errors=[],[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs={pool.submit(acquire_one,out,v):v for v in versions}
        for i,future in enumerate(as_completed(jobs),1):
            v=jobs[future]
            try:records.append(future.result())
            except Exception as exc:errors.append(dict(path=v['path'],commit=v['commit'],error=type(exc).__name__))
            if i%25==0:print(json.dumps(dict(completed=i,total=len(versions),errors=len(errors))),flush=True)
    records.sort(key=lambda r:(r['season'],r['committer_at'],r['revision']))
    report=dict(version='fixture-history-v1',repository=REPOSITORY,pinned_revision=REVISION,
        git_log_sha256=digest(log_bytes),implementation_sha256=digest(Path(__file__).read_bytes()),
        expected_versions=len(versions),records=records,errors=errors,deleted_versions=excluded,
        bytes=sum(r['bytes'] for r in records),distinct_objects=len({r['sha256'] for r in records}),
        eligible_predeadline=False,production_changed=False,limitation='Git_commit_time_is_not_verified_publication_time')
    (out/'manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--log',type=Path,required=True);ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args();r=build(a.log,a.out);print(json.dumps({k:v for k,v in r.items() if k!='records'},indent=2))
    if r['errors']:raise SystemExit(1)


if __name__=='__main__':main()
