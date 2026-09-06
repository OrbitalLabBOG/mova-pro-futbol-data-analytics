import hashlib
import sqlite3

from experiments.data_ground_truth.sqlite_sidecar_audit import classify


def test_sidecar_requires_bound_sqlite_parent_and_preserves_nonempty_wal(tmp_path):
    (tmp_path/'objects').mkdir();db=tmp_path/'source.db3'
    connection=sqlite3.connect(db);connection.execute('create table t(x)');connection.close()
    data=db.read_bytes();sha=hashlib.sha256(data).hexdigest();(tmp_path/'objects'/sha).write_bytes(data)
    records=[dict(sha256=sha,bytes=len(data),path='source.db3')]
    wal=tmp_path/'objects'/(sha+'-wal');wal.write_bytes(b'not empty')
    result=classify(wal.name,records,tmp_path)
    assert result['status']=='sqlite_named_auxiliary' and result['empty_wal'] is False
    assert result['new_source_observation'] is False
    assert classify(wal.name,[],tmp_path)['status']=='unclassified'
    assert classify('unknown',records,tmp_path)['status']=='unclassified'
