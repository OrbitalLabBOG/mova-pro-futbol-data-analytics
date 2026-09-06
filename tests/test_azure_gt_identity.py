import pandas as pd
import pytest
from experiments.data_ground_truth.azure_gt_identity import link


def test_reused_season_id_does_not_override_official_code():
    gt=pd.DataFrame([dict(element=671,official_player_code=465390)])
    result=link([dict(id=671,code=490098)],gt)
    assert result.iloc[0].identity_status=='code_absent_from_gt_with_id_conflict'
    assert pd.isna(result.iloc[0].gt_element)
    assert link([dict(id=671,code=465390)],gt).iloc[0].gt_element==671


def test_duplicate_and_conflicting_identity_cannot_fan_out():
    gt=pd.DataFrame([dict(element=1,official_player_code=10),dict(element=2,official_player_code=20)])
    result=link([dict(id=1,code=20)],gt)
    assert result.iloc[0].identity_status=='season_id_code_conflict'
    assert pd.isna(result.iloc[0].gt_element)
    result=link([dict(id=1,code=10),dict(id=1,code=10)],gt)
    assert result.gt_element.isna().all()
    with pytest.raises(ValueError,match='ambiguous'):
        link([dict(id=1,code=10)],pd.concat([gt,pd.DataFrame([dict(element=1,official_player_code=20)])]))
