from experiments.data_ground_truth.workshop_source_audit import read_csv,candidates,FIELDS


def test_malformed_csv_does_not_produce_shifted_profiles():
    report,rows=read_csv(b'name,minutes\nA,90,unexpected\n')
    assert report['status']=='invalid_shape' and rows==[]
    report,rows=read_csv(b'name,minutes\n"A, B",90\n')
    assert report['status']=='rectangular' and rows[0]['name']=='A, B'


def test_name_match_is_candidate_and_ambiguity_is_not_resolved():
    row=dict(first_name='A',second_name='B',**{k:'0' for k in FIELDS})
    p=dict(row,id=1,code=42)
    result=candidates([row],[p])[0]
    assert result['status']=='unique_name_candidate' and not result['verified_identity']
    assert not result['eligible_training'] and result['available_at'] is None
    result=candidates([row],[p,dict(p,id=2,code=99)])[0]
    assert result['status']=='ambiguous_name' and 'candidate_code' not in result
