import csv
import gzip
import io
import json
import pytest
from experiments.data_ground_truth import profile_identity_promotion as promotion
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import verify


def source_package(tmp_path,monkeypatch,entity='player'):
    row=dict(element='1',fixture='8',gw='38',minutes='0',total_points='0',season='2014-15',entity_type=entity,
             official_player_code='',source_official_player_code='',identity_key='fpl:2014-15:1',available_at='',eligible_predeadline='False')
    text=io.StringIO();w=csv.DictWriter(text,fieldnames=list(row),lineterminator='\n');w.writeheader();w.writerow(row)
    payload=gzip.compress(text.getvalue().encode(),mtime=0)
    m=dict(version='fpl-labels-v8',rows=1,manager_rows=0,partitions=[dict(season='2014-15',file='2014-15.csv.gz',rows=1,sha256=digest(payload))])
    m['dataset_id']=digest(json.dumps(m,sort_keys=True,separators=(',',':')).encode())
    root=tmp_path/'training-datasets'/m['dataset_id'];root.mkdir(parents=True)
    (root/'manifest.json').write_text(json.dumps(m));(root/'2014-15.csv.gz').write_bytes(payload)
    monkeypatch.setattr(promotion,'PARENT_ID',m['dataset_id']);return root,row


def test_derivation_preserves_labels_and_is_reproducible(tmp_path,monkeypatch):
    root,original=source_package(tmp_path,monkeypatch)
    accepted=[dict(player_id=1,source_code=123,status='corroborated_code_and_full_name',reference_rows=1)]
    a,changes=promotion.derive(tmp_path,accepted,'evidence',tmp_path/'a')
    b,_=promotion.derive(tmp_path,accepted,'evidence',tmp_path/'b')
    assert a==b and len(changes)==1
    left=tmp_path/'a'/a['dataset_id'];right=tmp_path/'b'/b['dataset_id']
    assert (left/'2014-15.csv.gz').read_bytes()==(right/'2014-15.csv.gz').read_bytes()
    row=next(csv.DictReader(io.StringIO(gzip.decompress((left/'2014-15.csv.gz').read_bytes()).decode())))
    assert row['official_player_code']=='123' and row['identity_key']=='opta:123'
    for key in original:
        if key not in {'official_player_code','source_official_player_code','identity_key'}:assert row[key]==original[key]
    assert verify(root)['dataset_id']==promotion.PARENT_ID


def test_v8_verifier_rejects_nonplayer_partition(tmp_path,monkeypatch):
    root,_=source_package(tmp_path,monkeypatch,entity='assistant_manager')
    with pytest.raises(ValueError,match='non-player'):verify(root)
