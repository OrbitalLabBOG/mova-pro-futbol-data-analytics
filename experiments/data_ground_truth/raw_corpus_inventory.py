"""Audit all manifest-based raw corpora without conflating copies with new data."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import verify


def objects(record):
    if 'sha256' in record and 'bytes' in record:
        return [(record['sha256'],record['bytes'])]
    if 'files' in record:
        if set(record['files'])!={'bootstrap-static.json','fixtures.json'}:
            raise ValueError('collector payload allowlist mismatch')
        return [(v['sha256'],v['bytes']) for v in record['files'].values()]
    raise ValueError('unsupported raw record schema')


def verify_object(root,sha,size):
    if not isinstance(sha,str) or not re.fullmatch('[0-9a-f]{64}',sha):
        raise ValueError('invalid object digest')
    if type(size) is not int or size<0:
        raise ValueError('invalid object size')
    path=root/'objects'/sha
    if path.stat().st_size!=size:raise ValueError('object size mismatch')
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    if h.hexdigest()!=sha:raise ValueError('object content mismatch')


def build(base,out,pointer):
    relative=out.resolve().relative_to(base.resolve()) if out.resolve().is_relative_to(base.resolve()) else None
    if relative is not None and (not relative.parts or relative.parts[0].startswith('raw')):
        raise ValueError('audit output must not use raw corpus namespace')
    manifests=sorted(base.glob('raw*/manifest.json'))
    if not manifests:raise ValueError('no raw manifests')
    inventories=[];global_objects={};physical_bytes=0;physical_objects=0
    for path in manifests:
        data=path.read_bytes();manifest=json.loads(data);records=manifest['records'];seen={};repositories=Counter()
        for record in records:
            repositories[record.get('repository',record.get('source','unknown'))]+=1
            for sha,size in objects(record):
                if sha in seen and seen[sha]!=size:raise ValueError('inconsistent object metadata')
                if sha not in seen:verify_object(path.parent,sha,size)
                seen[sha]=size
                if sha in global_objects and global_objects[sha]!=size:raise ValueError('cross-corpus size mismatch')
                global_objects[sha]=size
        physical_objects+=len(seen);physical_bytes+=sum(seen.values())
        files={p.name for p in (path.parent/'objects').iterdir() if p.is_file()}
        inventories.append(dict(corpus=path.parent.name,manifest_sha256=digest(data),records=len(records),
                                declared_expected_files=manifest.get('expected_files'),
                                declared_file_count_matches=manifest.get('expected_files',len(records))==len(records),
                                acquisition_errors=len(manifest.get('errors',[])),repositories=dict(repositories),
                                verified_objects=len(seen),verified_bytes=sum(seen.values()),
                                unreferenced_object_files=len(files-set(seen)),
                                record_schema='collector_public_files' if records and 'files' in records[0] else 'content_addressed_record'))
    other_layouts=[]
    for root in sorted(p for p in base.glob('raw*') if p.is_dir() and not (p/'manifest.json').exists()):
        for path in sorted(p for p in root.rglob('*') if p.is_file()):
            if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                raise ValueError('other-layout file escapes corpus')
            data=path.read_bytes()
            other_layouts.append(dict(corpus=root.name,path=path.relative_to(root).as_posix(),
                                      sha256=digest(data),bytes=len(data),verification='observed_hash_baseline_only'))
    pointer_bytes=pointer.read_bytes();current=json.loads(pointer_bytes)
    package=base/'training-datasets'/current['dataset_id']
    if digest((package/'manifest.json').read_bytes())!=current['manifest_sha256']:
        raise ValueError('current label pointer hash mismatch')
    label=verify(package)
    if label['dataset_id']!=current['dataset_id']:raise ValueError('current label identity mismatch')
    out.mkdir(parents=True,exist_ok=True)
    inventory_bytes=(json.dumps(inventories,indent=2)+'\n').encode();(out/'corpora.json').write_bytes(inventory_bytes)
    object_bytes=(json.dumps(global_objects,sort_keys=True,indent=2)+'\n').encode();(out/'object-index.json').write_bytes(object_bytes)
    other_bytes=(json.dumps(other_layouts,indent=2)+'\n').encode();(out/'other-layout-index.json').write_bytes(other_bytes)
    result=dict(version='raw-corpus-inventory-v1',implementation_sha256=digest(Path(__file__).read_bytes()),
                corpora=len(inventories),records=sum(r['records'] for r in inventories),
                physical_referenced_objects=physical_objects,physical_referenced_bytes=physical_bytes,
                unique_content_objects=len(global_objects),unique_content_bytes=sum(global_objects.values()),
                other_layout_files=len(other_layouts),other_layout_bytes=sum(r['bytes'] for r in other_layouts),
                corpora_with_acquisition_errors=[r['corpus'] for r in inventories if r['acquisition_errors']],
                corpora_with_declared_count_mismatch=[r['corpus'] for r in inventories if not r['declared_file_count_matches']],
                raw_directories_without_manifest=sorted(p.name for p in base.glob('raw*') if p.is_dir() and not (p/'manifest.json').exists()),
                current_labels=dict(pointer_sha256=digest(pointer_bytes),dataset_id=label['dataset_id'],
                                    rows=label['rows'],manager_rows=label['manager_rows'],seasons=[p['season'] for p in label['partitions']]),
                artifacts={'corpora.json':digest(inventory_bytes),'object-index.json':digest(object_bytes),
                           'other-layout-index.json':digest(other_bytes)},
                production_changed=False,training_admitted=False,
                limitations=['other_layout_files_have_observed_hash_baseline_not_manifest_validation',
                             'all_versions_counted_including_superseded_corpora',
                             'unique_bytes_not_unique_sporting_observations',
                             'collector_account_payloads_not_read_or_exported',
                             'integrity_does_not_prove_semantics_publication_licensing_or_training_eligibility'])
    (out/'report.json').write_text(json.dumps(result,indent=2)+'\n');return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('base-root','out','label-pointer'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();r=build(a.base_root,a.out,a.label_pointer);print(json.dumps(r,indent=2))


if __name__=='__main__':main()
