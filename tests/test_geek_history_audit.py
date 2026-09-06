import pytest
from experiments.data_ground_truth.geek_history_audit import decode,FIELDS


def sample():
    row=dict(id=1,code=42,first_name='A',second_name='B',team_id=2,element_type_id=1,
        now_cost=50,minutes=90,total_points=6,event_points=6,status='a',added='2015-01-01',last_season_points=70)
    names=list(reversed(FIELDS))
    return dict(elStat={n:i for i,n in enumerate(names)},elInfo=[None,[row[n] for n in names]],
        eiwteams={'2':{'code':8}},picks=['must not export'])


def test_source_mapping_controls_decoding_without_private_selection():
    row=decode(sample())[0]
    assert row['id']==1 and row['code']==42 and row['minutes']==90 and row['team_code']==8
    assert 'picks' not in row and row['available_at'] is None and not row['eligible_predeadline']


def test_ambiguous_mapping_and_duplicate_identity_rejected():
    payload=sample();payload['elStat']['code']=payload['elStat']['id']
    with pytest.raises(ValueError,match='ambiguous'):
        decode(payload)
    payload=sample();payload['elInfo'].append(payload['elInfo'][1])
    with pytest.raises(ValueError,match='duplicate'):
        decode(payload)
