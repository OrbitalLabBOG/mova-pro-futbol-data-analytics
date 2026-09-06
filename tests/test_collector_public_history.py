import io
import json
import tarfile
from pathlib import Path

import pytest

from experiments.data_ground_truth.collector_public_export import PUBLIC_FILES,archive,bundle,sha,unpack
from experiments.data_ground_truth.collector_public_audit import completion,select


def source(tmp_path):
    root=tmp_path/'raw';directory=root/'2026-27'/'capture';directory.mkdir(parents=True)
    files={}
    for name,data in [('bootstrap-static.json',b'{}'),('fixtures.json',b'[]'),('entry.json',b'account-body-excluded')]:
        (directory/name).write_bytes(data);files[name]=dict(bytes=len(data),sha256=sha(data))
    manifest=dict(source='fpl_official',method='GET',season='2026-27',schema='mova-data-source-v1',
                  observed_at='2026-08-28T12:00:00Z',payload_sha256='bundle',files=files)
    (directory/'manifest.json').write_text(json.dumps(manifest))
    return root,directory


def test_export_contains_only_public_bodies_and_original_manifest_metadata(tmp_path):
    root,directory=source(tmp_path);stream=io.BytesIO();archive(root,'2026-08-29T00:00:00Z',stream)
    path=tmp_path/'bundle.tar.gz';path.write_bytes(stream.getvalue());m=unpack(path,tmp_path/'out')
    assert set(m['records'][0]['files'])==set(PUBLIC_FILES)
    assert m['objects']==2 and m['source_manifests']==1 and not m['account_payloads_exported']
    assert all(p.read_bytes()!=b'account-body-excluded' for p in (tmp_path/'out/objects').iterdir())
    original=tmp_path/'out/source-manifests'/m['records'][0]['source_manifest_sha256']
    assert original.read_bytes()==(directory/'manifest.json').read_bytes()
    again=io.BytesIO();archive(root,'2026-08-29T00:00:00Z',again)
    assert stream.getvalue()==again.getvalue()


def test_corrupt_public_source_and_unsafe_tar_are_rejected(tmp_path):
    root,directory=source(tmp_path);(directory/'fixtures.json').write_bytes(b'changed')
    with pytest.raises(ValueError,match='hash/size'):bundle(root,'2026-08-29T00:00:00Z')
    path=tmp_path/'bad.tar.gz'
    with tarfile.open(path,'w:gz') as tar:
        item=tarfile.TarInfo('../escape');item.size=1;tar.addfile(item,io.BytesIO(b'x'))
    with pytest.raises(ValueError,match='member'):unpack(path,tmp_path/'out')
    assert not (tmp_path/'escape').exists()


def ledger():
    record=dict(source_path='/capture',source_manifest_sha256='manifest',source_payload_sha256='bundle',observed_at='2026-08-28T12:00:00Z')
    run=dict(artifact_path='/capture',manifest_sha256='manifest',payload_sha256='bundle',source_name='fpl_official',
             status='completed',started_at='2026-08-28T12:00:01Z',finished_at='2026-08-28T12:00:05Z',run_id='run')
    return record,run


def test_availability_uses_completed_ingestion_not_collection_start():
    record,run=ledger();proof=completion(record,[run]);assert proof['available_at']=='2026-08-28T12:00:05+00:00'
    target=dict(season='2026-27',gw=2,deadline='2026-08-28T12:00:04Z')
    row=dict(record,**proof,season='2026-27',deadlines={'2':target['deadline']})
    assert select([row],target) is None
    target['deadline']='2026-08-28T12:00:05Z';row['deadlines']['2']=target['deadline']
    assert select([row],target) is None
    target['deadline']='2026-08-28T12:00:06Z';row['deadlines']['2']=target['deadline']
    assert select([row],target) is row


def test_ledger_conflicts_fail_closed():
    record,run=ledger()
    for bad in [dict(run,status='failed'),dict(run,payload_sha256='other'),dict(run,finished_at=None),dict(run,finished_at='2026-08-28T11:59:00Z')]:
        with pytest.raises(ValueError):completion(record,[bad])
    with pytest.raises(ValueError,match='ambiguous'):completion(record,[run,run])
