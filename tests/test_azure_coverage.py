import json
from experiments.data_ground_truth.azure_coverage import measure


def row(name='2020-09-12T08-00-00Z_data.json',download='2020-09-12 08:00:00.100000'):
    data=dict(download_time=download,elements=[dict(id=1)],events=[dict(id=1,deadline_time='2020-09-12T10:00:00Z')])
    record=dict(listing_item=dict(name=name),content_summary=dict(season='2020-21'),sha256='a',url='source',response_last_modified='Sat, 31 Jul 2021 18:28:03 GMT')
    return record,json.dumps(data).encode()


def test_late_blob_metadata_does_not_become_predeadline_proof():
    r,data=row();s,windows=measure([r],lambda _:data)
    assert s['seasons']['2020-21']['gameweek_coverage_by_max_age_hours']=={'1':0,'6':1,'24':1,'168':1}
    assert windows[0]['blob_last_modified_before_deadline'] is False
    assert windows[0]['available_at'] is None
    assert not windows[0]['eligible_predeadline']


def test_future_or_disagreeing_clocks_do_not_create_candidates():
    r,data=row(download='2020-09-11 08:00:00')
    s,w=measure([r],lambda _:data)
    assert not w
    assert s['wall_clock_status']['missing_or_disagreeing_wall_clock']==1
    r,data=row(name='2020-09-12T11-00-00Z_data.json',download='2020-09-12 11:00:00')
    assert not measure([r],lambda _:data)[1]


def test_deadline_changes_remain_distinct_and_null_chance_is_counted():
    r,data=row();v=json.loads(data)
    v['events'].append(dict(id=1,deadline_time='2020-09-12T11:00:00Z'))
    v['elements'][0]['chance_of_playing_next_round']=None
    summary,windows=measure([r],lambda _:json.dumps(v).encode())
    assert len(windows)==2
    assert summary['seasons']['2020-21']['nonnull_player_fields']['chance_of_playing_next_round']==0
    assert summary['seasons']['2020-21']['gameweek_coverage_by_max_age_hours']['24']==1
