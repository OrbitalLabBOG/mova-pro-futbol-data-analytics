import sqlite3
from experiments.data_ground_truth.footieviz_source_audit import compare,sqlite_counts
from experiments.data_ground_truth.raw import select


def test_identity_and_null_points_never_become_zero():
    row=['date',1,'ARS(H) 0-0',0]+[0]*15+[None]
    source=dict(id=1,code=42,fixture_history={'all':[row]})
    baseline=dict(source,fixture_history={'all':[row[:-1]+[0]]})
    result=compare([source],[baseline])[0]
    assert result['different_columns']==[19] and result['source_row'][-1] is None
    assert not result['eligible_training']
    assert compare([source],[dict(baseline,code=99)])[0]['status']=='identity_mismatch'


def test_sqlite_inventory_does_not_execute_views_or_modify_source(tmp_path):
    path=tmp_path/'sample.db'
    with sqlite3.connect(path) as connection:
        connection.execute('create table Players(id integer)')
        connection.execute('create view invalid_view as select * from missing_table')
    before=path.read_bytes()
    assert sqlite_counts(path)=={'Players':0} and path.read_bytes()==before
    assert select('sandalsoft/footieviz_py','sqlalchemy_example.db')
    assert not select('sandalsoft/footieviz_py','migratedb.aws.sh')
