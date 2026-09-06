import pytest
from experiments.data_ground_truth.kickoff_semantics import compare


def test_diagnostic_preserves_scheduled_and_updated_clocks():
    rows=[dict(element=1,fixture=263,gw=27,event_time_utc='2022-02-26T15:00:00Z')]
    fixture=dict(id=263,event=27,kickoff_time='2022-02-26T15:30:00Z')
    counts,delta=compare(rows,[fixture])
    assert counts['compared_rows']==1
    assert delta[0]['delta_seconds']==1800
    assert rows[0]['event_time_utc']=='2022-02-26T15:00:00Z'
    assert fixture['kickoff_time']=='2022-02-26T15:30:00Z'
    with pytest.raises(ValueError,match='duplicate fixture'):compare(rows,[fixture,fixture])


def test_equivalent_offsets_unknowns_and_missing_references():
    rows=[dict(element=1,fixture=1,gw=1,event_time_utc='2022-08-01T16:00:00+01:00'),
          dict(element=2,fixture=1,gw=1,event_time_utc=None),
          dict(element=3,fixture=2,gw=1,event_time_utc=None)]
    counts,delta=compare(rows,[dict(id=1,event=1,kickoff_time='2022-08-01T15:00:00Z')])
    assert not delta
    assert counts=={'compared_rows':1,'unknown_time':1,'missing_reference':1}
