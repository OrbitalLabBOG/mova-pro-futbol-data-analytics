import pandas as pd
import pytest

from experiments.data_ground_truth.correction_history import assess
from tests.test_gw2_period import row


def frame(time='2025-02-01T12:00:00Z'):
    return pd.DataFrame([dict(row(24,1,10,17),event_time_utc=time)])


def test_residual_preserves_original_value_and_marks_near_kickoff():
    result=assess(dict(code=10,element_type=3,minutes=0),frame(),['minutes'],'2025-02-01T13:00:00',10)
    assert result['status']=='different'
    assert result['cells']['minutes']['residual']==-17
    assert result['cells']['minutes']['observed']['value']==0
    assert result['kickoff_within_four_hours'] is True


def test_absence_identity_unknown_time_and_missing_component_remain_unknown():
    e=dict(code=10,element_type=3)
    assert assess(None,frame(),['minutes'],'2025-02-02T00:00:00',10)['status']=='absent_element'
    assert assess(dict(e,code=20),frame(),['minutes'],'2025-02-02T00:00:00',10)['status']=='identity_or_entity_mismatch'
    assert assess(e,frame(None),['minutes'],'2025-02-02T00:00:00',10)['status']=='unknown_event_time'
    assert assess(e,frame(),['minutes'],'2025-02-02T00:00:00',10)['status']=='unknown_component'
    with pytest.raises(ValueError,match='unzoned'):
        assess(e,frame(),['minutes'],'2025-02-02T00:00:00Z',10)
