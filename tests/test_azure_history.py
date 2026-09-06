import base64
import hashlib
import json

import pytest

from experiments.data_ground_truth.azure_history import listing, validate, capture


def blob():
    data=json.dumps(dict(events=[dict(id=i,deadline_time='2020-09-12T10:00:00Z',is_current=i==1) for i in range(1,39)],elements=[],teams=[])).encode()
    record=dict(bytes=len(data),content_md5=base64.b64encode(hashlib.md5(data).digest()).decode())
    return data,record


def test_content_season_and_integrity_do_not_depend_on_filename():
    data,record=blob()
    record['name']='2019-01-01T00-00-00Z_data.json'
    assert validate(data,record)['season']=='2020-21'
    with pytest.raises(ValueError,match='differs'):
        validate(data+b' ',record)
    data=json.dumps(dict(events=[],elements=[],teams=[])).encode()
    record.update(bytes=len(data),content_md5=base64.b64encode(hashlib.md5(data).digest()).decode())
    with pytest.raises(ValueError,match='event universe'):
        validate(data,record)


def test_listing_rejects_truncation_unsafe_names_and_duplicates():
    template='<EnumerationResults><Blobs>{}</Blobs><NextMarker>{}</NextMarker></EnumerationResults>'
    row='<Blob><Name>2020-01-01T00-00-00Z_data.json</Name><Properties><Content-Length>4</Content-Length><Content-MD5>AAAAAAAAAAAAAAAAAAAAAA==</Content-MD5></Properties></Blob>'
    assert len(listing(template.format(row,'').encode(),'2020-fpl-data'))==1
    for body in [template.format(row,'next'),template.format(row+row,''),template.format(row.replace('2020-01-01T00-00-00Z_data.json','../x'),'')]:
        with pytest.raises(ValueError):
            listing(body.encode(),'2020-fpl-data')


def test_capture_revalidates_cache_and_never_admits_time(tmp_path,monkeypatch):
    data,item=blob();item['name']='2020-01-01T00-00-00Z_data.json'
    monkeypatch.setattr('experiments.data_ground_truth.azure_history._get',lambda *a,**k:(data,{}))
    result=capture(tmp_path,'2020-fpl-data',item,False)
    assert result['available_at'] is None
    assert not result['eligible_training']
    assert capture(tmp_path,'2020-fpl-data',item,True)==result
    (tmp_path/'objects'/result['sha256']).write_bytes(b'changed')
    with pytest.raises(ValueError):
        capture(tmp_path,'2020-fpl-data',item,True)
