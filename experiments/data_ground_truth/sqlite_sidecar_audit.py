"""Classify SQLite-named raw auxiliaries without treating them as acquisitions."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile

from experiments.data_ground_truth.differential_audit import read_tables
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.raw_corpus_inventory import verify_object


def classify(name,records,root):
    match=re.fullmatch('([0-9a-f]{64})-(wal|shm)',name)
    if not match:return dict(status='unclassified')
    parent,kind=match.groups()
    sources=[r for r in records if r.get('sha256')==parent and r['path'].endswith('.db3')]
    if not sources:return dict(status='unclassified')
    for source in sources:verify_object(root,parent,source['bytes'])
    with (root/'objects'/parent).open('rb') as stream:
        if stream.read(16)!=b'SQLite format 3\x00':return dict(status='unclassified')
    data=(root/'objects'/name).read_bytes()
    return dict(status='sqlite_named_auxiliary',kind=kind,parent_sha256=parent,
                source_paths=sorted(r['path'] for r in sources),bytes=len(data),sha256=digest(data),
                empty_wal=(not data) if kind=='wal' else None,
                creation_process_proven=False,new_source_observation=False)


def fingerprints(root):
    return {p.name:digest(p.read_bytes()) for p in sorted(root.iterdir()) if p.is_file()}


def build(root,out):
    manifest_bytes=(root/'manifest.json').read_bytes();manifest=json.loads(manifest_bytes)
    records=manifest['records'];known={r['sha256'] for r in records}
    before=fingerprints(root/'objects')
    extras=sorted(set(before)-known)
    classifications=[dict(file=name,**classify(name,records,root)) for name in extras]
    parents=sorted({r['parent_sha256'] for r in classifications if r['status']=='sqlite_named_auxiliary'})
    checks=[]
    for parent in parents:
        related=[r for r in classifications if r.get('parent_sha256')==parent]
        if any(r['kind']=='wal' and not r['empty_wal'] for r in related):
            checks.append(dict(parent_sha256=parent,status='nonempty_wal_requires_review'));continue
        original=read_tables(root/'objects'/parent)
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary);copy=directory/'archive.db3'
            shutil.copyfile(root/'objects'/parent,copy)
            copied_hash=digest(copy.read_bytes());copied=read_tables(copy)
            if copied_hash!=parent or digest(copy.read_bytes())!=parent:
                raise ValueError('immutable copy changed')
            if set(p.name for p in directory.iterdir())!={'archive.db3'}:
                raise ValueError('immutable reader created sidecars')
            if any(not original[t].equals(copied[t]) for t in original):
                raise ValueError('standalone database differs from original')
            checks.append(dict(parent_sha256=parent,status='standalone_immutable_read_equal',
                               tables={t:dict(rows=len(frame),columns=list(frame.columns),
                                              content_sha256=digest(frame.to_json(orient='split',index=False,double_precision=15).encode()))
                                       for t,frame in copied.items()},sidecars_created=0))
    if fingerprints(root/'objects')!=before or (root/'manifest.json').read_bytes()!=manifest_bytes:
        raise ValueError('raw archive changed during audit')
    out.mkdir(parents=True,exist_ok=True)
    result=dict(version='sqlite-sidecar-audit-v1',manifest_sha256=digest(manifest_bytes),
                implementation_sha256=digest(Path(__file__).read_bytes()),
                reader_implementation_sha256=digest(Path(__file__).with_name('differential_audit.py').read_bytes()),
                unreferenced_files=len(extras),classifications=classifications,standalone_checks=checks,
                raw_unchanged=True,training_admitted=False,production_changed=False,
                limitations=['file_naming_and_parent_binding_do_not_identify_creation_process',
                             'nonempty_WAL_must_not_be_ignored_or_removed',
                             'auxiliaries_preserved_not_deleted',
                             'no_new_labels_or_seasons'])
    (out/'report.json').write_text(json.dumps(result,indent=2)+'\n');return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('raw-root','out'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();r=build(a.raw_root,a.out);print(json.dumps(dict(unreferenced_files=r['unreferenced_files'],checks=[x['status'] for x in r['standalone_checks']])) )


if __name__=='__main__':main()
