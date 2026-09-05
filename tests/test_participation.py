import numpy as np
import pandas as pd
import pytest

from mova_fpl.models.participation import CONTEXT, ParticipationModel, context
from mova_fpl.engine.projection import _proba_minutos


def frame():
    return pd.DataFrame({"player_key": ["a"] * 6, "element": [1] * 6,
        "season": ["2024-25"] * 3 + ["2025-26"] * 3, "gw": [1, 2, 3] * 2,
        "fixture": range(6), "minutes": [0, 0, 20, 90, 90, 0],
        "starts": [0, 0, 0, 1, 1, 0], "value": [50] * 6,
        "position": ["MID"] * 6, "was_home": [1] * 6})


def test_context_excludes_target_and_all_future_results():
    a = frame()
    b = a.copy()
    b.loc[3:, ["minutes", "starts"]] = [999, 1]
    pd.testing.assert_frame_equal(context(a).iloc[:4], context(b).iloc[:4])
    assert context(a)["current_season_observations"].tolist() == [0, 1, 2, 0, 1, 2]


def test_training_and_live_context_are_equal():
    class Recorder:
        def predict_proba(self, d):
            self.d = d.copy()
            return np.tile([.2, .3, .5], (len(d), 1))
    d = frame()
    recorder = Recorder()
    m = ParticipationModel(_modelo=recorder)
    for i in range(1, len(d)):
        m.predict_proba_history(d.iloc[:i], d.iloc[[i]])
        np.testing.assert_allclose(recorder.d[CONTEXT].iloc[0], context(d)[CONTEXT].iloc[i], equal_nan=True)


def test_missing_starts_is_not_invented_as_zero():
    c = context(frame().drop(columns="starts"))
    assert c["recent_start_rate"].isna().all()
    assert c["starts_missing"].eq(1).all()


def test_projection_rejects_invalid_new_model_probabilities():
    class Bad:
        def predict_proba_history(self, history, roster):
            return np.tile([-.1, .5, .6], (len(roster), 1))
    with pytest.raises(ValueError, match="invalid participation"):
        _proba_minutos(frame(), frame().iloc[:1], Bad())
