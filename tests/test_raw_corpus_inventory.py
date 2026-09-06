import hashlib
import pytest

from experiments.data_ground_truth.raw_corpus_inventory import build,objects,verify_object


def test_same_size_corruption_is_detected(tmp_path):
    payload=b'original';sha=hashlib.sha256(payload).hexdigest()
    (tmp_path/'objects').mkdir();p=tmp_path/'objects'/sha;p.write_bytes(payload)
    verify_object(tmp_path,sha,len(payload))
    p.write_bytes(b'corrupt!')
    with pytest.raises(ValueError,match='content'):verify_object(tmp_path,sha,len(payload))
    with pytest.raises(ValueError,match='digest'):verify_object(tmp_path,'../escape',8)


def test_collector_only_exposes_allowlisted_public_payloads():
    meta=dict(sha256='a'*64,bytes=1)
    r=dict(files={'bootstrap-static.json':meta,'fixtures.json':meta},source_payload_sha256='private_reference')
    assert objects(r)==[('a'*64,1),('a'*64,1)]
    r['files']['account.json']=meta
    with pytest.raises(ValueError,match='allowlist'):objects(r)
    with pytest.raises(ValueError,match='unsupported'):objects({'path':'unknown'})


def test_audit_output_cannot_become_an_input_corpus(tmp_path):
    with pytest.raises(ValueError,match='raw corpus namespace'):
        build(tmp_path,tmp_path/'raw-audit',tmp_path/'pointer.json')
