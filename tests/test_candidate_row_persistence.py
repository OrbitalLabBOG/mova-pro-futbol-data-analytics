from experiments.data_ground_truth.candidate_row_persistence import CASES,observe,summarize


def test_identity_and_fixture_context_required_for_zero():
    case=CASES[0];row=[case['date'],case['gw'],case['opponent']+' ',0]+[0]*16
    p=dict(id=case['element'],code=case['code'],web_name='Name',team_name='Team',team_code=8,status='a',fixture_history={'all':[row]})
    result=observe({str(case['element']):p},case)
    assert result['status']=='row_present' and not result['eligible_training']
    assert observe({str(case['element']):dict(p,code=999)},case)['status']=='identity_mismatch'
    assert observe({str(case['element']):dict(p,fixture_history={'all':[row[:2]+['OTHER(A) ']+row[3:]]})},case)['status']=='row_absent'


def test_disappearance_does_not_confirm_finalized_zero():
    base=dict(path='x',sha256='hash',nominal_filename_time='2015-08',source_team_code=8)
    present=dict(base,status='row_present',candidate_row=['date',1,'opp',0]+[0]*16)
    absent=dict(base,status='row_absent',candidate_row=None,source_team_code=57,nominal_filename_time='2015-09')
    report=summarize([present,absent])
    assert len(report['transitions'])==2 and report['last_snapshot_status']=='row_absent'
    assert not report['final_observation_proven'] and not report['eligible_training']
