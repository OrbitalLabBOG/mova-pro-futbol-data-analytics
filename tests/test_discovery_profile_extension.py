import pytest
from experiments.data_ground_truth.discovery_profile_extension import profiles


def source():
    return dict(sha256='source',repository='repo',revision='revision',path='Data/FPL_API_Dump.json')


def profile():
    return dict(code=101,id=1,web_name='Smith',first_name='Alex',second_name='Smith')


def test_dump_retains_code_full_name_and_source_provenance():
    result=profiles({'Smith':profile()},source())
    assert result[0]['code']==101 and result[0]['first_name']=='Alex'
    assert result[0]['source_sha256']=='source'
    assert 'available_at' not in result[0]


def test_duplicate_codes_ids_and_mismatched_display_keys_rejected():
    for dump in [{'Smith':profile(),'Jones':dict(profile(),id=2,web_name='Jones')},
                 {'Smith':profile(),'Jones':dict(profile(),code=102,web_name='Jones')},
                 {'Other':profile()}, {'Smith':dict(profile(),first_name='')}]:
        with pytest.raises(ValueError):profiles(dump,source())
