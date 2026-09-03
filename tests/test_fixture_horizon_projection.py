"""Contrato causal del proyector compartido por replay y sombra viva."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mova_fpl.engine import projection as subject


class _Minutes:
    pass


class _Points:
    def __init__(self):
        self.prepared_calls = 0
        self.project_calls = 0

    def prepare_history(self, history):
        self.prepared_calls += 1
        return {"frozen_at_rows": len(history)}

    def project(self, history, roster, probabilities, scoring, thresholds,
                equipos=None, prepared=None):
        self.project_calls += 1
        strength = {"B": 2.0, "C": 5.0}
        xp = np.asarray([
            strength[equipos[int(opponent)]] * float(p60)
            for opponent, p60 in zip(roster["opponent_team"], probabilities[:, 2])
        ])
        return pd.DataFrame({
            "element": roster["element"].to_numpy(),
            "xp": xp,
            "xp_sd": xp / 2.0,
        })


def test_fixture_horizon_uses_future_rival_with_one_frozen_player_state(monkeypatch):
    monkeypatch.setattr(
        subject,
        "_proba_minutos",
        lambda history, roster, model: np.asarray([[0.0, 0.0, 1.0]]),
    )
    history = pd.DataFrame([{"season": "2025-26", "gw": 38}])
    roster = pd.DataFrame([{
        "season": "2026-27", "gw": 1, "element": 10, "player_key": "p",
        "name": "P", "position": "MID", "team": "A", "value": 80,
        "opponent_team": 2, "was_home": 1, "fixture": 101,
    }])
    schedule = pd.DataFrame([
        {"gw": 1, "fixture": 101, "team": "A", "opponent_team": 2,
         "was_home": 1, "kickoff_time": None},
        {"gw": 1, "fixture": 101, "team": "B", "opponent_team": 1,
         "was_home": 0, "kickoff_time": None},
        {"gw": 2, "fixture": 102, "team": "C", "opponent_team": 1,
         "was_home": 1, "kickoff_time": None},
        {"gw": 2, "fixture": 102, "team": "A", "opponent_team": 3,
         "was_home": 0, "kickoff_time": None},
    ])
    points = _Points()

    result = subject.fixture_horizon_projection(
        history=history, roster=roster,
        modelos={"minutes": _Minutes(), "points": points},
        season="2026-27", gw=1, horizon=2, schedule=schedule, decay=0.8,
        disponibilidad=np.asarray([0.5]),
    )

    assert result.horizon_xp[1][10] == pytest.approx(1.0)
    assert result.horizon_xp[2][10] == pytest.approx(2.0)
    assert result.horizon_sd[2][10] == pytest.approx(1.0)
    assert result.current_detail.loc[0, "n_fixtures"] == 1
    assert points.prepared_calls == 1
    assert points.project_calls == 2
