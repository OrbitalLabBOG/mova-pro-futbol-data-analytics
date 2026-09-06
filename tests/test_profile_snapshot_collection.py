import hashlib
import pytest
from experiments.data_ground_truth.profile_snapshot_collection import PIN,describe,describe_payload,inventory,verify_blob


def test_git_blob_integrity_and_tree_scope():
    payload=b'{}';entry=dict(path='data/players.1.json',type='blob',size=2,sha=hashlib.sha1(b'blob 2\0{}').hexdigest())
    verify_blob(payload,entry)
    with pytest.raises(ValueError,match='mismatch'):verify_blob(b'[]',entry)
    tree=dict(sha=PIN,truncated=False,tree=[entry,dict(entry,path='config.json')])
    assert inventory(tree)==[entry]
    with pytest.raises(ValueError):inventory(dict(tree,truncated=True))
    with pytest.raises(ValueError):inventory(dict(tree,tree=[entry,entry]))


def test_history_projection_distinguishes_outcomes_from_profile_mutations():
    p=dict(id=1,code=123,fixture_history={'all':[['date',1,'opp']+[0]*17]},season_history=[['2013/14']],ep_this='4')
    first=describe({'1':p});second=describe({'1':dict(p,ep_this='8')})
    assert first['history_sha256']==second['history_sha256']
    changed=dict(p,fixture_history={'all':[['date',1,'opp']+[0]*16+[2]]})
    assert describe({'1':changed})['history_sha256']!=first['history_sha256']
    assert first['history_rows']==1 and not first['publication_proven']
    assert describe({})['status']=='empty'
    assert describe({'2':p})['status']=='profile_id_mismatch'
    assert describe({'1':dict(p,fixture_history={'all':[[1]]})})['status']=='unsupported_row_schema'


def test_incomplete_source_json_is_recorded_without_inventing_rows():
    result=describe_payload(b'{"1": ')
    assert result['status']=='invalid_json' and result['profiles'] is None
    assert result['error_type']=='JSONDecodeError'
    assert 'history_rows' not in result
