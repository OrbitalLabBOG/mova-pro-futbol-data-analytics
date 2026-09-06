from experiments.data_ground_truth.differential_null_lineage import OUTCOMES, summarize
from experiments.data_ground_truth.raw import select


def test_forecast_does_not_resolve_unknown_outcomes():
    row=dict.fromkeys(OUTCOMES);row.update(gameweek=38,has_forecast=1)
    report=summarize([row])
    assert report['unknown_minutes_without_any_selected_outcome']==1
    assert report['unknown_minutes_with_forecast']==1
    assert report['new_observed_labels']==0
    assert not report['null_to_zero_admitted']
    assert row['minutes'] is None


def test_explicit_zero_and_partial_outcome_are_distinct():
    a=dict.fromkeys(OUTCOMES);a.update(gameweek=34,has_forecast=0,minutes=0,total=0)
    b=dict(a,minutes=45,total=None)
    c=dict(a,minutes=None,total=2)
    report=summarize([a,b,c])
    assert report['known_minutes_missing_points']==1
    assert report['unknown_minutes']==1
    assert report['unknown_minutes_without_any_selected_outcome']==0
    assert select('sjp4/differentialfpl','Differential/src/com/pennas/fpl/process/ProcessPlayer.java')
    assert not select('sjp4/differentialfpl','Differential/src/com/pennas/fpl/process/Unreviewed.java')
