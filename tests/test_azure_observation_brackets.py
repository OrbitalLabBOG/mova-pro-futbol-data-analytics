import json
from experiments.data_ground_truth.azure_observation_brackets import scan, classification


def test_code_change_does_not_rewrite_native_observation():
    records=[];objects={}
    for hour,players in [('06',[]),('12',[dict(id=1,code=90)]),('18',[dict(id=1,code=10)])]:
        records.append(dict(sha256=hour,url=hour,content_summary=dict(season='2020-21'),listing_item=dict(name=f'2020-09-12T{hour}-00-00Z_data.json')))
        objects[hour]=json.dumps(dict(download_time=f'2020-09-12 {hour}:00:00',elements=players)).encode()
    histories,excluded=scan(records,{('2020-21',1,10)},objects.__getitem__)
    h=histories[('2020-21',1,10)]
    assert not excluded
    assert h['first_native']['observed_code']==90
    assert h['first_exact']['observed_code']==10
    assert h['last_without_exact']['source_sha256']=='12'
    deadline='2020-09-12T15:00:00+00:00'
    assert classification(h,deadline,'native')=='first_observed_before_deadline'
    assert classification(h,deadline,'exact')=='observation_interval_straddles_deadline'
    assert h['first_exact']['available_at'] is None


def test_no_lower_bound_or_no_observation_is_not_registration_proof():
    first=dict(nominal_time='2020-09-12T18:00:00+00:00')
    h=dict(first_native=first,last_without_native=None)
    assert classification(h,'2020-09-12T15:00:00+00:00','native')=='first_observed_at_or_after_deadline_without_lower_bound'
    h['last_without_native']=dict(nominal_time='2020-09-12T16:00:00+00:00')
    assert classification(h,'2020-09-12T15:00:00+00:00','native')=='absent_in_snapshot_at_or_after_deadline'
    h['first_native']=None
    assert classification(h,'2020-09-12T15:00:00+00:00','native')=='not_observed_in_archive'
