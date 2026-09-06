"""Portable internal archive cut with explicit source groups and atomic restoration."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import tempfile

from experiments.data_ground_truth.azure_history import ACCOUNT, CONTAINERS
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.raw_bundle import canonical, hashfile, safe, verify_bundle
from experiments.data_ground_truth.training_dataset import checked

GROUPS=('source_extension','statsbomb_research')


def inventory(root):
    if root.is_symlink() or not root.is_dir():raise ValueError('regular source directory required')
    result=[]
    for path in sorted(root.rglob('*')):
        if path.is_symlink():raise ValueError('source symlink forbidden')
        if not path.is_file():continue
        relative=path.relative_to(root).as_posix();safe(relative)
        if any(p.startswith('.') for p in Path(relative).parts) or relative.endswith('.tmp'):
            raise ValueError('hidden or unfinished file in source directory')
        sha,size=hashfile(path);result.append(dict(path=relative,sha256=sha,bytes=size))
    return result


def merge_files(manifests):
    merged={}
    for manifest in manifests:
        for row in manifest['files']:
            safe(row['path']);previous=merged.get(row['path'])
            if previous is not None and (previous['sha256'],previous['bytes'])!=(row['sha256'],row['bytes']):
                raise ValueError('conflicting restoration path across archive groups')
            merged[row['path']]=row
    return merged


def data_references(manifest):
    if isinstance(manifest,list):records=manifest
    elif 'records' in manifest:records=manifest['records']
    elif 'sources' in manifest:
        records=[r['source'] for r in manifest['sources']]
    elif 'sha256' in manifest:records=[manifest]
    else:records=[]
    references=[];failed=0
    for row in records:
        if 'error' in row:failed+=1;continue
        if 'sha256' in row and 'bytes' in row:references.append((row['sha256'],row['bytes']))
        elif 'listing_item' in row and 'sha256' in row:
            item=row['listing_item'];container=row.get('container')
            if container not in CONTAINERS or row.get('url')!=ACCOUNT+'/'+container+'/'+item.get('name',''):
                raise ValueError('unreviewed Azure source reference')
            if type(item.get('bytes')) is not int or item['bytes']<=0:raise ValueError('invalid Azure source size')
            references.append((row['sha256'],item['bytes']))
        elif 'compressed_sha256' in row:references.append((row['compressed_sha256'],row['compressed_bytes']))
        else:raise ValueError('unsupported documentary source record')
    return references,failed


def plan(base, registry_path, repository_root):
    registry_bytes=registry_path.read_bytes();registry=json.loads(registry_bytes)
    legacy_path=base/registry['legacy']['path'];safe(registry['legacy']['path'])
    legacy_manifest=checked(legacy_path/'manifest.json',registry['legacy']['manifest_sha256'])
    legacy=verify_bundle(legacy_path)
    if legacy['bundle_id']!=registry['legacy']['bundle_id']:raise ValueError('different legacy bundle')
    groups={g:{} for g in GROUPS};sources={g:{} for g in GROUPS};directories=[];references=[];failed_records=0
    def add(group,source,relative,sha,size,role):
        if group not in GROUPS:raise ValueError('unknown archive group')
        safe(relative)
        if relative.startswith(('statsbomb-','legacy-scoring-audit-')) and group!='statsbomb_research':
            raise ValueError('StatsBomb corpus cannot enter general source extension')
        if hashfile(source)!=(sha,size):raise ValueError('archive input differs from pinned source')
        row=dict(path=relative,sha256=sha,bytes=size,role=role)
        if relative in groups[group] and groups[group][relative]!=row:raise ValueError('duplicate archive path')
        groups[group][relative]=row;sources[group].setdefault(sha,source)
    for entry in registry['directories']:
        name=entry['directory'];safe(name)
        if len(Path(name).parts)!=1 or name.startswith(('EXP-','raw-production')):raise ValueError('non-research directory prohibited')
        root=base/name;items=inventory(root)
        if digest(canonical(items))!=entry['inventory_sha256']:raise ValueError('directory drift: '+name)
        for item in items:add(entry['group'],root/item['path'],name+'/'+item['path'],item['sha256'],item['bytes'],entry['role'])
        if (root/'manifest.json').exists():
            manifest=json.loads((root/'manifest.json').read_text());refs,failed=data_references(manifest)
            references.extend(dict(directory=name,sha256=sha,bytes=size) for sha,size in refs);failed_records+=failed
        if (root/'report.json').exists():
            report=json.loads((root/'report.json').read_text())
            for name_,sha in report.get('artifacts',{}).items():
                safe(name_);checked(root/name_,sha)
        directories.append(dict(**entry,files=len(items),bytes=sum(i['bytes'] for i in items)))
    for entry in registry['files']:
        if entry['origin'] not in ('repository','base'):raise ValueError('unknown explicit source origin')
        safe(entry['source']);root=repository_root if entry['origin']=='repository' else base
        source=root/entry['source']
        if not source.resolve().is_relative_to(root.resolve()):raise ValueError('explicit source escapes root')
        add(entry['group'],source,entry['path'],entry['sha256'],entry['bytes'],entry['role'])
    manifests=[legacy];descriptors={}
    for group in GROUPS:
        descriptor=dict(version='data-archive-group-v1',group=group,files=sorted(groups[group].values(),key=lambda r:r['path']),
            registry_sha256=digest(registry_bytes),implementation_sha256=digest(Path(__file__).read_bytes()),
            training_admitted=False,publication_authorized=False,commercial_runtime_admitted=False,
            rights='StatsBomb_research_only' if group=='statsbomb_research' else 'source_specific_rights_not_collectively_cleared')
        manifest=dict(descriptor,bundle_id=digest(canonical(descriptor)));descriptors[group]=manifest;manifests.append(manifest)
    merged=merge_files(manifests);index={r['sha256']:r['bytes'] for r in merged.values()}
    for ref in references:
        if index.get(ref['sha256'])!=ref['bytes']:raise ValueError('declared source bytes absent from complete cut: '+ref['directory'])
    members=[dict(group='legacy_g55',bundle_id=legacy['bundle_id'],manifest_sha256=digest(legacy_manifest))]
    members.extend(dict(group=g,bundle_id=m['bundle_id'],manifest_sha256=digest(canonical(m))) for g,m in descriptors.items())
    descriptor=dict(version='data-archive-cut-v1',members=members,registry_sha256=digest(registry_bytes),
        implementation_sha256=digest(Path(__file__).read_bytes()),restoration_paths=len(merged),
        unique_content_objects=len(index),unique_content_bytes=sum(index.values()),directories=directories,
        verified_source_references=len(references),failed_acquisition_receipts_preserved=failed_records,
        gt_dataset_id=legacy['gt_dataset_id'],training_admitted=False,publication_authorized=False,
        offsite_backup_verified=False,production_changed=False,
        limitations=['selected_source_and_lineage_archive_not_all_model_experiment_workspaces',
            'local_restore_does_not_prove_offsite_backup_or_predeadline_availability',
            'failed_acquisition_receipt_is_not_recovered_source_data',
            'StatsBomb_and_general_source_groups_do_not_share_publication_permissions'])
    cut=dict(descriptor,cut_id=digest(canonical(descriptor)))
    return cut,legacy_path,descriptors,sources


def verify(package):
    cut=json.loads((package/'cut.json').read_text());descriptor={k:v for k,v in cut.items() if k!='cut_id'}
    if digest(canonical(descriptor))!=cut['cut_id']:raise ValueError('archive cut identity mismatch')
    if len(cut['members'])!=3 or {m['group'] for m in cut['members']}!={'legacy_g55',*GROUPS}:raise ValueError('archive group set differs')
    manifests=[]
    for member in cut['members']:
        if len(member['bundle_id'])!=64 or any(c not in '0123456789abcdef' for c in member['bundle_id']):raise ValueError('invalid member ID')
        root=package/'bundles'/member['bundle_id'];checked(root/'manifest.json',member['manifest_sha256'])
        manifest=verify_bundle(root)
        if manifest['bundle_id']!=member['bundle_id']:raise ValueError('archive member mismatch')
        if member['group']!='legacy_g55' and (manifest.get('group')!=member['group'] or manifest.get('publication_authorized') is not False):
            raise ValueError('archive group contract differs')
        if member['group']!='statsbomb_research' and any(r['path'].startswith(('statsbomb-','legacy-scoring-audit-')) for r in manifest['files']):
            raise ValueError('restricted data outside research group')
        manifests.append(manifest)
    merged=merge_files(manifests)
    if len(merged)!=cut['restoration_paths']:raise ValueError('archive path count differs')
    contents={r['sha256']:r['bytes'] for r in merged.values()}
    if len(contents)!=cut['unique_content_objects'] or sum(contents.values())!=cut['unique_content_bytes']:
        raise ValueError('archive content counts differ')
    return cut,manifests


def build(base, registry, repository_root, out):
    if out.resolve()==base.resolve():raise ValueError('archive output cannot be acquisition base')
    if out.resolve().is_relative_to(base.resolve()) and out.resolve().relative_to(base.resolve()).parts[0].startswith('raw'):
        raise ValueError('archive output cannot enter raw namespace')
    cut,legacy_path,manifests,sources=plan(base,registry,repository_root)
    if any(out.resolve().is_relative_to((base/d['directory']).resolve()) for d in cut['directories']):
        raise ValueError('archive output cannot enter a source directory')
    target=out/cut['cut_id']
    if target.exists():verify(target);return target
    out.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.building-',dir=out) as tmp:
        stage=Path(tmp)/'cut';(stage/'bundles').mkdir(parents=True)
        shutil.copytree(legacy_path,stage/'bundles'/cut['members'][0]['bundle_id'])
        for group,manifest in manifests.items():
            root=stage/'bundles'/manifest['bundle_id'];(root/'objects').mkdir(parents=True)
            for sha,source in sources[group].items():shutil.copyfile(source,root/'objects'/sha)
            (root/'manifest.json').write_bytes(canonical(manifest))
        (stage/'cut.json').write_bytes(canonical(cut));verify(stage);stage.rename(target)
    return target


def restore(package,out):
    cut,manifests=verify(package)
    if out.exists() or out.is_symlink():raise ValueError('restore requires a new destination')
    if out.resolve().is_relative_to(package.resolve()):raise ValueError('restore cannot modify archive package')
    merged=merge_files(manifests);sources={}
    for manifest in manifests:
        for row in manifest['files']:sources.setdefault(row['sha256'],package/'bundles'/manifest['bundle_id']/'objects'/row['sha256'])
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.restoring-',dir=out.parent) as tmp:
        stage=Path(tmp)/'restored';stage.mkdir()
        for relative,row in merged.items():
            target=stage/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(sources[row['sha256']],target)
            if hashfile(target)!=(row['sha256'],row['bytes']):raise ValueError('restored content differs')
        stage.rename(out)
    return dict(cut_id=cut['cut_id'],restored_files=len(merged),offsite_backup_verified=False)


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    b=sub.add_parser('build')
    for name in ('base','registry','repository-root','out'):b.add_argument('--'+name,type=Path,required=True)
    for command in ('verify','restore'):
        q=sub.add_parser(command);q.add_argument('--package',type=Path,required=True)
        if command=='restore':q.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    if a.command=='build':print(build(a.base,a.registry,a.repository_root,a.out))
    elif a.command=='verify':print(verify(a.package)[0]['cut_id'])
    else:print(json.dumps(restore(a.package,a.out)))


if __name__=='__main__':main()
