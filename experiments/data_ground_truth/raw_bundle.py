"""Portable internal raw corpus bundle with content deduplication and verified restoration."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tempfile

from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.raw_corpus_inventory import objects
from experiments.data_ground_truth.training_dataset import checked, verify


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()


def safe(path):
    p = PurePosixPath(path)
    if not path or p.is_absolute() or '..' in p.parts or str(p) != path or '\\' in path:
        raise ValueError('unsafe bundle path')
    return p


def hashfile(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('bundle inputs must be regular files')
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest(), path.stat().st_size


def plan(base):
    inventory = base / 'corpus-inventory-v4'
    audit_path = Path(__file__).with_name('results-g50.json')
    audit = json.loads(audit_path.read_text())
    # The G50 result pins the report; all inventories are transitively bound below.
    expected = audit['audit_report_sha256']
    report = json.loads(checked(inventory / 'report.json', expected))
    corpora = json.loads(checked(inventory / 'corpora.json', report['artifacts']['corpora.json']))
    other = json.loads(checked(inventory / 'other-layout-index.json', report['artifacts']['other-layout-index.json']))
    entries = {}; sources = {}; excluded = []
    def add(path, relative, sha=None, size=None, role='raw'):
        safe(relative)
        actual, length = hashfile(path)
        if sha is not None and actual != sha or size is not None and length != size:
            raise ValueError('input no longer matches recorded evidence: ' + relative)
        item = dict(path=relative, sha256=actual, bytes=length, role=role)
        if relative in entries and entries[relative] != item:
            raise ValueError('conflicting restoration path')
        entries[relative] = item
        sources.setdefault(actual, path)
    for c in corpora:
        root = base / c['corpus']
        manifest = json.loads(checked(root / 'manifest.json', c['manifest_sha256']))
        add(root / 'manifest.json', c['corpus'] + '/manifest.json', c['manifest_sha256'], role='acquisition_manifest')
        for record in manifest['records']:
            for sha, size in objects(record):
                relative = c['corpus'] + '/objects/' + sha
                if relative not in entries:
                    add(root / 'objects' / sha, relative, sha, size)
    for item in other:
        relative = item['corpus'] + '/' + item['path']
        if item['corpus'] == 'raw-production-discovery-v1':
            excluded.append(dict(path=relative, reason='operative_discovery_not_public_research_corpus'))
        else:
            add(base / relative, relative, item['sha256'], item['bytes'], 'observed_baseline_not_acquisition_proof')
    sidecars = json.loads(Path(__file__).with_name('results-g51.json').read_text())['audit']['classifications']
    for item in sidecars:
        relative = 'raw-history-differential/objects/' + item['file']
        add(base / relative, relative, item['sha256'], item['bytes'], 'preserved_sqlite_auxiliary_not_new_observation')
    for name in ('literature-discovery-g52', 'official-chip-evidence-g54'):
        root = base / name
        manifest_bytes = (root / 'manifest.json').read_bytes()
        gate = json.loads(Path(__file__).with_name('results-g52.json' if name.endswith('g52') else 'results-g54.json').read_text())
        expected = gate['literature' if name.endswith('g52') else 'documentary_sources']['manifest_sha256']
        if digest(manifest_bytes) != expected:
            raise ValueError('documentary manifest mismatch')
        add(root / 'manifest.json', name + '/manifest.json', expected, role='documentary_manifest')
        for item in json.loads(manifest_bytes)['records']:
            add(root / 'objects' / item['sha256'], name + '/objects/' + item['sha256'], item['sha256'], item['bytes'], 'documentary_context')
    pointer_path = Path(__file__).with_name('current-labels.json')
    pointer = json.loads(pointer_path.read_text())
    package = base / 'training-datasets' / pointer['dataset_id']
    checked(package / 'manifest.json', pointer['manifest_sha256'])
    verify(package)
    for path in sorted(package.iterdir()):
        add(path, 'training-datasets/' + pointer['dataset_id'] + '/' + path.name, role='retrospective_gt')
    add(pointer_path, 'metadata/current-labels.json', role='experimental_gt_pointer')
    for gate in (50, 51, 52, 53, 54):
        path = Path(__file__).with_name(f'results-g{gate}.json')
        add(path, 'metadata/' + path.name, role='versioned_audit_result')
    descriptor = dict(version='internal-raw-bundle-v1', files=sorted(entries.values(), key=lambda r: r['path']),
                      excluded=excluded, gt_dataset_id=pointer['dataset_id'],
                      implementation_sha256=digest(Path(__file__).read_bytes()),
                      scope='G50_referenced_public_corpora_other_public_layouts_GT_and_G52_G54_documents',
                      production_changed=False, training_admitted=False, publication_authorized=False,
                      limitations=['local_copy_is_not_an_offsite_backup', 'acquisition_cache_and_derived_audit_directories_not_included',
                                   'bundle_integrity_does_not_establish_temporal_semantics_or_license',
                                   'retrospective_GT_is_not_a_predeadline_feature_table'])
    return descriptor, sources


def verify_bundle(package):
    manifest = json.loads((package / 'manifest.json').read_text())
    descriptor = {k: v for k, v in manifest.items() if k != 'bundle_id'}
    if digest(canonical(descriptor)) != manifest['bundle_id']:
        raise ValueError('bundle identity mismatch')
    seen = set(); hashes = {}
    for entry in manifest['files']:
        safe(entry['path'])
        if entry['path'] in seen:
            raise ValueError('duplicate restoration path')
        seen.add(entry['path'])
        sha = entry['sha256']
        if len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha):
            raise ValueError('invalid content hash')
        if sha not in hashes:
            hashes[sha] = hashfile(package / 'objects' / sha)
        if hashes[sha] != (sha, entry['bytes']):
            raise ValueError('bundle object corruption')
    return manifest


def build(base, root):
    if root.resolve().is_relative_to(base.resolve()):
        relative = root.resolve().relative_to(base.resolve())
        if not relative.parts or relative.parts[0].startswith('raw'):
            raise ValueError('bundle output must not enter the raw acquisition namespace')
    descriptor, sources = plan(base)
    bundle_id = digest(canonical(descriptor))
    target = root / bundle_id
    if target.exists():
        if verify_bundle(target)['bundle_id'] != bundle_id:
            raise ValueError('existing bundle does not match target identity')
        return target
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.building-', dir=root) as tmp:
        stage = Path(tmp) / 'bundle'; stage.mkdir(); (stage / 'objects').mkdir()
        for sha, source in sources.items():
            shutil.copyfile(source, stage / 'objects' / sha)
        (stage / 'manifest.json').write_bytes(canonical(dict(descriptor, bundle_id=bundle_id)))
        verify_bundle(stage)
        stage.rename(target)
    return target


def restore(package, out):
    manifest = verify_bundle(package)
    if out.exists():
        raise ValueError('restore requires a new destination')
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.restoring-', dir=out.parent) as tmp:
        stage = Path(tmp) / 'restored'; stage.mkdir()
        for entry in manifest['files']:
            target = stage / entry['path']; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(package / 'objects' / entry['sha256'], target)
            if hashfile(target) != (entry['sha256'], entry['bytes']):
                raise ValueError('restored file corruption')
        stage.rename(out)
    return dict(bundle_id=manifest['bundle_id'], restored_files=len(manifest['files']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('build'); p.add_argument('--base-root', type=Path, required=True); p.add_argument('--out', type=Path, required=True)
    p = sub.add_parser('restore'); p.add_argument('--package', type=Path, required=True); p.add_argument('--out', type=Path, required=True)
    p = sub.add_parser('verify'); p.add_argument('--package', type=Path, required=True)
    a = parser.parse_args()
    if a.command == 'build': print(build(a.base_root, a.out))
    elif a.command == 'restore': print(json.dumps(restore(a.package, a.out)))
    else: print(verify_bundle(a.package)['bundle_id'])


if __name__ == '__main__':
    main()
