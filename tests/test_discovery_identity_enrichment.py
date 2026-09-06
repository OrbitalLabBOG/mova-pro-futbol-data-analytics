import pytest
from experiments.data_ground_truth.discovery_identity_enrichment import classify,update_rows


def candidate():
    return dict(player_id=1,source_code=101,reference_rows=1,profile=dict(first_name='Matthew',second_name='Smith'))


def test_code_alone_and_fuzzy_name_do_not_admit_identity():
    c=candidate()
    assert classify(c,[])['status']=='no_later_profile'
    assert classify(c,[dict(code=101,first_name='Matt',second_name='Smith')])['status']=='name_variant_requires_review'
    assert classify(c,[dict(code=102,first_name='Matthew',second_name='Smith')])['status']=='no_later_profile'
    assert classify(c,[dict(code=101,first_name='MATTHEW',second_name='Smith')])['status']=='corroborated_code_and_full_name'
    empty=dict(c,profile=dict(first_name='',second_name=''))
    assert classify(empty,[dict(code=101,first_name='',second_name='')])['status']=='name_variant_requires_review'


def row():
    return dict(element='1',fixture='11',season='2014-15',entity_type='player',official_player_code='',source_official_player_code='',
                identity_key='fpl:2014-15:1',minutes='0',total_points='0',available_at='',eligible_predeadline='False')


def accepted():
    return dict(candidate(),status='corroborated_code_and_full_name')


def test_enrichment_changes_only_identity_and_preserves_input():
    original=row();enriched,changes=update_rows([original],[accepted()])
    assert original['official_player_code']==''
    assert enriched[0]['official_player_code']=='101' and len(changes)==1
    for key in ('minutes','total_points','available_at','eligible_predeadline'):
        assert enriched[0][key]==original[key]


def test_existing_identity_collision_and_wrong_population_rejected():
    with pytest.raises(ValueError,match='unresolved'):
        update_rows([dict(row(),official_player_code='102')],[accepted()])
    other=dict(row(),element='2',official_player_code='101',source_official_player_code='101',identity_key='opta:101')
    with pytest.raises(ValueError,match='assigned'):update_rows([row(),other],[accepted()])
    with pytest.raises(ValueError,match='population'):update_rows([row()],[dict(accepted(),reference_rows=2)])


@pytest.mark.parametrize('version',['fpl-labels-v5','fpl-labels-v6'])
def test_player_partition_guard_remains_active_in_derived_gt(tmp_path,version):
    import csv,gzip,io,json
    from experiments.data_ground_truth.raw import digest
    from experiments.data_ground_truth.training_dataset import verify
    r=dict(row(),entity_type='assistant_manager')
    stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=list(r));writer.writeheader();writer.writerow(r)
    data=gzip.compress(stream.getvalue().encode(),mtime=0);(tmp_path/'part.csv.gz').write_bytes(data)
    manifest=dict(version=version,rows=1,partitions=[dict(file='part.csv.gz',season='2014-15',rows=1,sha256=digest(data))])
    manifest['dataset_id']=digest(json.dumps(manifest,sort_keys=True,separators=(',',':')).encode())
    (tmp_path/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='non-player'):verify(tmp_path)
