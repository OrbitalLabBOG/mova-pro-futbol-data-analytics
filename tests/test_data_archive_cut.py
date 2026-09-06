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


def test_azure_references_use_pinned_listing_size_and_reject_other_hosts():
    from experiments.data_ground_truth.data_archive_cut import data_references
    row=dict(sha256='a'*64,container='2020-fpl-data',listing_item=dict(name='2020-01-01T00-00-00Z_data.json',bytes=12),
        url='https://martinfplstats1337.blob.core.windows.net/2020-fpl-data/2020-01-01T00-00-00Z_data.json')
    assert data_references(dict(records=[row]))==([('a'*64,12)],0)
    with pytest.raises(ValueError,match='unreviewed'):
        data_references(dict(records=[row|{'url':'https://example.org/other'}]))
    with pytest.raises(ValueError,match='size'):
        data_references(dict(records=[row|{'listing_item':row['listing_item']|{'bytes':True}}]))


def test_archive_recomputes_content_counts_even_with_rehashed_descriptor(tmp_path):
    base,registry=fixture_registry(tmp_path);package=build(base,registry,tmp_path,tmp_path/'packages')
    cut=json.loads((package/'cut.json').read_text());cut['unique_content_bytes']+=1
    cut['cut_id']=digest(canonical({k:v for k,v in cut.items() if k!='cut_id'}))
    (package/'cut.json').write_bytes(canonical(cut))
    with pytest.raises(ValueError,match='content counts'):
        verify(package)


def test_active_gt_requires_restorable_partitions_and_retains_legacy_identity(tmp_path):
    import gzip
    base,registry_path=fixture_registry(tmp_path)
    payload=gzip.compress(b'season,element,fixture,eligible_predeadline,available_at,entity_type\n2014-15,1,8,False,,player\n',mtime=0)
    descriptor=dict(version='fpl-labels-v8',rows=1,manager_rows=0,partitions=[dict(file='2014-15.csv.gz',sha256=digest(payload),season='2014-15',rows=1)])
    dataset_id=digest(json.dumps(descriptor,sort_keys=True,separators=(',',':')).encode())
    manifest=json.dumps(dict(descriptor,dataset_id=dataset_id)).encode()
    relative='training-datasets/'+dataset_id;root=base/relative;root.mkdir(parents=True)
    registry=json.loads(registry_path.read_text())
    for name,data in [('manifest.json',manifest),('2014-15.csv.gz',payload)]:
        (root/name).write_bytes(data)
        registry['files'].append(dict(origin='base',source=relative+'/'+name,path=relative+'/'+name,group='source_extension',role='test_gt',sha256=digest(data),bytes=len(data)))
    registry['active_gt']=dict(path=relative,dataset_id=dataset_id,manifest_sha256=digest(manifest));registry_path.write_text(json.dumps(registry))
    package=build(base,registry_path,tmp_path,tmp_path/'packages');cut,_=verify(package)
    assert cut['gt_dataset_id']==dataset_id and cut['legacy_gt_dataset_id']=='test-gt'
    restore(package,tmp_path/'restored')
    assert (tmp_path/'restored'/relative/'2014-15.csv.gz').read_bytes()==payload
    registry['files'].pop();registry_path.write_text(json.dumps(registry))
    with pytest.raises(ValueError,match='partition absent'):build(base,registry_path,tmp_path,tmp_path/'incomplete')
