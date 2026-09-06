"""Export only public bootstrap/fixtures bytes from collector manifests; no host writes."""
from __future__ import annotations
import argparse
from datetime import datetime
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tarfile

PUBLIC_FILES=('bootstrap-static.json','fixtures.json')


def sha(data):return hashlib.sha256(data).hexdigest()


def aware(value):
    result=datetime.fromisoformat(value.replace('Z','+00:00'))
    if result.tzinfo is None:raise ValueError('aware clock required')
    return result


def bundle(root,cutoff):
    root=root.resolve();records=[];objects={};manifests={}
    for path in sorted((root/'2026-27').glob('*/manifest.json')):
        if path.is_symlink() or not path.resolve().is_relative_to(root):raise ValueError('unsafe manifest path')
        manifest_bytes=path.read_bytes();m=json.loads(manifest_bytes)
        if aware(m['observed_at'])>aware(cutoff):continue
        if m['source']!='fpl_official' or m['method']!='GET' or m['season']!='2026-27' or m['schema']!='mova-data-source-v1':
            raise ValueError('unexpected source contract')
        manifests[sha(manifest_bytes)]=manifest_bytes
        files={}
        for name in PUBLIC_FILES:
            source=path.parent/name
            if source.is_symlink() or not source.resolve().is_relative_to(root):raise ValueError('unsafe public file path')
            data=source.read_bytes();h=sha(data);declared=m['files'][name]
            if h!=declared['sha256'] or len(data)!=declared['bytes']:raise ValueError('source file hash/size mismatch')
            objects[h]=data;files[name]=dict(sha256=h,bytes=len(data))
        records.append(dict(source_path=str(path.parent),source_manifest_sha256=sha(manifest_bytes),
                            source_payload_sha256=m['payload_sha256'],observed_at=m['observed_at'],
                            season=m['season'],source=m['source'],method=m['method'],files=files))
    if not records:raise ValueError('empty collector export')
    manifest=dict(version='collector-public-export-v1',cutoff=cutoff,records=records,objects=len(objects),
                  bytes=sum(map(len,objects.values())),exported_files=list(PUBLIC_FILES),
                  account_payloads_exported=False,source_manifests=len(manifests),source_payload_sha_is_reference_only=True,
                  limitations=['observed_at_is_collection_start_not_availability','original_manifests_are_provenance_metadata_with_public_team_reference'])
    return manifest,objects,manifests


def archive(root,cutoff,stream):
    manifest,objects,manifests=bundle(root,cutoff)
    entries={'manifest.json':(json.dumps(manifest,indent=2)+'\n').encode(),**{'objects/'+h:data for h,data in objects.items()},**{'source-manifests/'+h:data for h,data in manifests.items()}}
    with gzip.GzipFile(fileobj=stream,mode='wb',mtime=0) as gz:
        with tarfile.open(fileobj=gz,mode='w|') as tar:
            for name in sorted(entries):
                data=entries[name];info=tarfile.TarInfo(name);info.size=len(data);info.mtime=0;info.mode=0o644
                tar.addfile(info,io.BytesIO(data))


def unpack(source,out):
    out.mkdir(parents=True,exist_ok=True);seen=set()
    with tarfile.open(source,'r:gz') as tar:
        for member in tar:
            name=member.name
            if not member.isfile() or not re.fullmatch(r'manifest\.json|(?:objects|source-manifests)/[0-9a-f]{64}',name) or name in seen or member.size>32*1024*1024:
                raise ValueError('invalid export member')
            seen.add(name);data=tar.extractfile(member).read()
            if name!='manifest.json' and sha(data)!=name.split('/')[1]:raise ValueError('export object hash mismatch')
            path=out/name;path.parent.mkdir(parents=True,exist_ok=True)
            if path.exists() and path.read_bytes()!=data:raise ValueError('immutable export conflict')
            path.write_bytes(data)
    manifest=json.loads((out/'manifest.json').read_text());expected={'manifest.json'}
    for r in manifest['records']:
        h=r['source_manifest_sha256']
        if not isinstance(h,str) or not re.fullmatch('[0-9a-f]{64}',h):raise ValueError('invalid source manifest hash')
        name='source-manifests/'+h
        if name not in seen:raise ValueError('missing source manifest')
        expected.add(name)
        if set(r['files'])!=set(PUBLIC_FILES):raise ValueError('unexpected exported file')
        for f in r['files'].values():
            if not isinstance(f.get('sha256'),str) or not re.fullmatch('[0-9a-f]{64}',f['sha256']):raise ValueError('invalid manifest hash')
            name='objects/'+f['sha256']
            if name not in seen:raise ValueError('missing manifest object')
            data=(out/name).read_bytes()
            if len(data)!=f['bytes'] or sha(data)!=f['sha256']:raise ValueError('manifest object mismatch')
            expected.add(name)
    if seen!=expected or sum(n.startswith('objects/') for n in expected)!=manifest['objects'] or sum(n.startswith('source-manifests/') for n in expected)!=manifest['source_manifests']:raise ValueError('export inventory mismatch')
    return manifest


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path);p.add_argument('--cutoff')
    p.add_argument('--unpack',type=Path);p.add_argument('--out',type=Path);a=p.parse_args()
    if a.unpack:
        if not a.out:p.error('--out required with --unpack')
        m=unpack(a.unpack,a.out);print(json.dumps(dict(records=len(m['records']),objects=m['objects'],bytes=m['bytes'])))
    else:
        if not a.root or not a.cutoff:p.error('--root and --cutoff required')
        archive(a.root,a.cutoff,sys.stdout.buffer)


if __name__=='__main__':main()
