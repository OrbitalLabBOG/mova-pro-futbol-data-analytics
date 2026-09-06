import pytest
from experiments.data_ground_truth.fixture_announcements import schedule


def test_bst_conversion_preserves_conditional_marker_and_source_positions():
    text='All times BST. Tuesday 10 May 20:00 Aston Villa v Liverpool (Sky Sports)*'
    row=schedule(text,2022,'BST',{'Aston Villa':2,'Liverpool':11})[0]
    assert row['kickoff_time']=='2022-05-10T19:00:00+00:00'
    assert row['conditional_as_printed'] and row['condition_marker']=='*'
    assert text[row['source_start']:row['source_end']]=='20:00 Aston Villa v Liverpool (Sky Sports)*'
    assert row['available_at'] is None and row['eligible_predeadline'] is False


def test_gmt_is_not_shifted_and_invalid_clock_or_weekday_is_not_silently_accepted():
    teams={'Arsenal':1,'Everton':8}
    text='Wednesday 1 March 19:45 GMT Arsenal v Everton'
    assert schedule(text,2023,'GMT',teams)[0]['kickoff_time']=='2023-03-01T19:45:00+00:00'
    for bad in (text.replace('Wednesday','Tuesday'),text.replace('Everton','Unknown Club')):
        with pytest.raises(ValueError):schedule(bad,2023,'GMT',teams)
    with pytest.raises(ValueError):schedule(text,2023,'BST',teams)
