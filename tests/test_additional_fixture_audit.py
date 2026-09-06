import json
import pytest
from experiments.data_ground_truth.additional_fixture_audit import read_fixture, signature


def test_season_signature_requires_complete_codes_and_preserves_team_identity():
    rows=[dict(id=i,code=1000+i,team_h=i,team_a=i+1) for i in range(1,381)]
    assert signature(rows)==signature(list(reversed(rows)))
    assert signature(rows[:-1]) is None
    missing=[dict(r) for r in rows];missing[0].pop('code')
    assert signature(missing) is None
    other=[dict(r) for r in rows];other[0]['team_h']=999
    assert signature(other)!=signature(rows)


def test_json_fixture_keeps_unknown_clock_and_omits_outcomes():
    fixture=dict(id=1,code=100,event=None,team_h=1,team_a=2,kickoff_time=None,started=False,team_h_score=5,stats=[])
    parsed=read_fixture(json.dumps([fixture]).encode(),'fixtures.json')
    assert parsed[0]['kickoff_time'] is None
    assert parsed[0]['event'] is None
    assert parsed[0]['started'] is False
    assert 'stats' not in parsed[0] and 'team_h_score' not in parsed[0]
    with pytest.raises(ValueError,match='schema'):read_fixture(b'id,event\n1,2\n','derived.csv')
