"""Temporal participation challenger. History is observed, never a future lineup.

Keeps the three scoring branches and the registered minutes artifact interface.
The extra state distinguishes recent role changes from a player's career mean.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.frozen import FrozenEstimator

from mova_fpl.models.features.minutes_features import FEATURES, build, build_targets
from mova_fpl.models.minutes import MinutesModel

CONTEXT = ["current_season_observations", "recent_start_rate", "recent_play_rate",
           "recent_60_rate", "recent_minutes", "role_delta", "starts_missing"]


def context(frame: pd.DataFrame) -> pd.DataFrame:
    """One shifted state per player-fixture; all targets exclude their own label."""
    d = frame.copy()
    d["player_key"] = d["player_key"].fillna("desconocido")
    d = d.sort_values(["player_key", "season", "gw", "fixture"])
    d["minutes"] = pd.to_numeric(d["minutes"], errors="coerce")
    d["starts"] = pd.to_numeric(d.get("starts", pd.Series(np.nan, index=d.index)),
                                errors="coerce")
    g = d.groupby("player_key", sort=False)
    out = pd.DataFrame(index=d.index)
    out["current_season_observations"] = d.groupby(["player_key", "season"]).cumcount()
    out["recent_start_rate"] = g["starts"].transform(
        lambda s: s.shift().rolling(4, min_periods=1).mean())
    out["recent_minutes"] = g["minutes"].transform(
        lambda s: s.shift().rolling(4, min_periods=1).mean())
    for key, threshold in (("recent_play_rate", 1), ("recent_60_rate", 60)):
        out[key] = g["minutes"].transform(
            lambda s: s.ge(threshold).astype(float).shift().rolling(4, min_periods=1).mean())
    career = g["minutes"].transform(lambda s: s.shift().expanding().mean())
    out["role_delta"] = out["recent_minutes"] - career
    out["starts_missing"] = out["recent_start_rate"].isna().astype(float)
    return out.reindex(frame.index)


@dataclass
class ParticipationModel(MinutesModel):
    version: str = "1.2.0"

    def fit(self, df: pd.DataFrame, calib_season: str | None = None):
        d = build(df)
        d[CONTEXT] = context(d)[CONTEXT]
        features = FEATURES + CONTEXT
        if calib_season is None or not (d["season"] < calib_season).any():
            raise ValueError("participation requires a separate temporal calibration season")
        if (d["season"] > calib_season).any():
            raise ValueError("calibration must be the final training season")
        train = d[d["season"] < calib_season]
        cal = d[d["season"] == calib_season]
        if cal.empty:
            raise ValueError("empty calibration season")
        base = HistGradientBoostingClassifier(
            max_iter=self.max_iter, learning_rate=self.learning_rate,
            random_state=self.random_state, early_stopping=False,
        ).fit(train[features].astype(float), train["y"])
        self._modelo = CalibratedClassifierCV(FrozenEstimator(base), method="isotonic")
        self._modelo.fit(cal[features].astype(float), cal["y"])
        self.metadata = {
            "features": features, "filas_ajuste": len(train),
            "filas_calibracion": len(cal), "calib_season": calib_season,
            "temporadas": sorted(d["season"].unique()),
            "state_contract": "participation-context-v1",
            "uncertainty": "calibrated P0/P1-59/P60; not injury diagnosis",
        }
        return self

    def predict_proba_built(self, d: pd.DataFrame) -> np.ndarray:
        if self._modelo is None:
            raise ValueError("model is not fitted")
        return self._normalizar(self._modelo.predict_proba(d[FEATURES + CONTEXT].astype(float)), len(d))

    def predict_proba_history(self, history: pd.DataFrame, roster: pd.DataFrame) -> np.ndarray:
        base = build_targets(history, roster)
        target = roster.copy()
        target["player_key"] = target["player_key"].fillna("desconocido")
        # The historical identity contract may share a key across elements.
        # Broadcast a single state; never let one target act as another's past.
        target = target.drop_duplicates("player_key")
        target["minutes"] = np.nan
        target["starts"] = np.nan
        target["_prediction_target"] = True
        past = history.copy()
        past["_prediction_target"] = False
        combined = pd.concat([past, target], ignore_index=True)
        extra = context(combined).loc[combined["_prediction_target"].eq(True)]
        extra.index = target["player_key"].to_numpy()
        base[CONTEXT] = extra.reindex(roster["player_key"].fillna("desconocido")).reset_index(drop=True)[CONTEXT]
        return self.predict_proba_built(base)

    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        d = build(df)
        d[CONTEXT] = context(d)[CONTEXT]
        return self.predict_proba_built(d)
