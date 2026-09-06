import pandas as pd
import pytest
from experiments.data_ground_truth.geek_season_context import candidate_season,compare


def test_roster_candidate_requires_unique_complete_set():
    assert candidate_season([1,2],{'a':{1,2},'b':{1,3}})=='a'
    assert candidate_season([1],{'a':{1,2}}) is None
    assert candidate_season([1,2],{'a':{1,2},'b':{1,2}}) is None


def test_code_conflict_is_not_repaired_or_matched_to_other_id():
    states=pd.DataFrame([dict(id=1,code=9),dict(id=3,code=8)])
    gt=pd.DataFrame([dict(element=1,official_player_code=8),dict(element=2,official_player_code=9)])
    rows=compare(states,gt)
    assert rows.identity_status.tolist()==['code_mismatch','missing_reference_id']
    assert rows.code.tolist()==[9,8]
    with pytest.raises(ValueError,match='ambiguous'):
        compare(states,pd.concat([gt,pd.DataFrame([dict(element=1,official_player_code=7)])]))
