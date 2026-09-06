import json
from pathlib import Path
import pytest
from experiments.data_ground_truth.data_archive_cut import build, inventory, merge_files, restore, verify
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.raw_bundle import canonical
from experiments.data_ground_truth.publication_source_archive import validate


def fixture_registry(tmp_path):
    base=tmp_path/'base';base.mkdir();legacy=base/'legacy';(legacy/'objects').mkdir(parents=True)
    payload=b'legacy bytes';sha=digest(payload);(legacy/'objects'/sha).write_bytes(payload)
    descriptor=dict(files=[dict(path='old/source',sha256=sha,bytes=len(payload))],gt_dataset_id='test-gt')
    manifest=dict(descriptor,bundle_id=digest(canonical(descriptor)));raw=canonical(manifest);(legacy/'manifest.json').write_bytes(raw)
    dirs=[]
    for name,group in [('document-source','source_extension'),('statsbomb-test','statsbomb_research')]:
        root=base/name;(root/'objects').mkdir(parents=True);data=name.encode();sha=digest(data);(root/'objects'/sha).write_bytes(data)
        (root/'manifest.json').write_text(json.dumps(dict(records=[dict(sha256=sha,bytes=len(data))])))
        dirs.append(dict(directory=name,group=group,role='test',inventory_sha256=digest(canonical(inventory(root)))))
    registry=tmp_path/'registry.json';registry.write_text(json.dumps(dict(legacy=dict(path='legacy',bundle_id=manifest['bundle_id'],manifest_sha256=digest(raw)),directories=dirs,files=[])))
    return base,registry


def test_archive_groups_restore_independent_copies_and_refuse_overwrite(tmp_path):
    base,registry=fixture_registry(tmp_path);package=build(base,registry,tmp_path,tmp_path/'packages')
    cut,_=verify(package);assert len(cut['members'])==3 and cut['verified_source_references']==2
    out=tmp_path/'restored';assert restore(package,out)['restored_files']==5
    (out/'old/source').write_bytes(b'local edit');verify(package)
    with pytest.raises(ValueError,match='new destination'):restore(package,out)
    target=next((package/'bundles'/cut['members'][1]['bundle_id']/'objects').iterdir());data=target.read_bytes();target.write_bytes(b'x'*len(data))
    with pytest.raises(ValueError):restore(package,tmp_path/'corrupt-restore')
    assert not (tmp_path/'corrupt-restore').exists()


def test_source_drift_symlinks_and_cross_group_collisions_fail_closed(tmp_path):
    base,registry=fixture_registry(tmp_path);(base/'document-source/extra.txt').write_text('unreviewed')
    with pytest.raises(ValueError,match='directory drift'):build(base,registry,tmp_path,tmp_path/'packages')
    root=tmp_path/'links';root.mkdir();(root/'link').symlink_to(registry)
    with pytest.raises(ValueError,match='symlink'):inventory(root)
    a=dict(path='same/path',sha256='a'*64,bytes=1);b=a|{'sha256':'b'*64}
    with pytest.raises(ValueError,match='conflicting'):merge_files([dict(files=[a]),dict(files=[b])])


def test_publication_fetch_requires_pinned_safe_source_before_network():
    record=dict(url='https://data.gharchive.org/2025-10-21-6.json.gz',compressed_sha256='a'*64,compressed_bytes=20)
    validate(record)
    for url in ('http://data.gharchive.org/2025-10-21-6.json.gz','https://example.org/data','https://data.gharchive.org/2025-10-21-6.json.gz?token=x'):
        with pytest.raises(ValueError):validate(record|{'url':url})
    with pytest.raises(ValueError):validate(record|{'compressed_sha256':'../other'})
