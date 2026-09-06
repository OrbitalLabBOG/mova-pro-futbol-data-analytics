from experiments.data_ground_truth.preseason_exception_history import observed, summarize
from experiments.data_ground_truth.preseason_performance import FIELDS


def element(code=10, kind=2, value=0):
    return dict(code=code, element_type=kind, **{f:value for f in FIELDS})


def observation(time, e):
    return dict(source_claimed_at=time, **observed(e,10))


def test_absence_and_identity_change_do_not_become_zero_performance():
    assert observed(None,10)['status']=='absent_element'
    assert observed(element(code=11),10)['status']=='identity_or_entity_mismatch'
    assert observed(element(kind=5),10)['status']=='identity_or_entity_mismatch'
    assert observed(element(),10)['cells']['minutes']==dict(status='valid',value=0)


def test_prior_match_remains_evidence_when_later_values_reset():
    rows=[observation('1',None),observation('2',element(value=3)),observation('3',element(value=0))]
    report=summarize(rows,{f:dict(prior_total=3) for f in FIELDS})
    assert report['matches_prior_totals']==1
    assert report['first_match']=='2'
    assert report['state_transitions']==2
    assert report['first_present']=='2'
    assert rows[-1]['cells']['minutes']['value']==0


def test_unknown_prior_total_never_matches_missing_snapshot_cell():
    row=observation('1',element())
    row['cells']['minutes']=dict(status='null',value=None)
    assert summarize([row],{'minutes':dict(prior_total=None)})['matches_prior_totals']==0
