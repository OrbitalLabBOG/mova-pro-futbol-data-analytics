"""Modelos experimentales y folds temporales para el laboratorio long-horizon."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from mova_fpl.models.goals import GoalsModel
from mova_fpl.models.minutes import MinutesModel
from mova_fpl.models.points import PointsModel
from mova_fpl.models.features.points_features import POSICIONES, normaliza_posicion


@dataclass
class EventProxyGoalsModel(GoalsModel):
    """Mezcla goles/xG con señales de volumen ``threat`` y ``creativity``.

    Los factores de escala se aprenden exclusivamente en temporadas anteriores
    al fold. ``threat`` y ``creativity`` existen en todo el histórico canónico y
    son proxies de eventos más estables que goles y asistencias observados. El
    peso cero es una réplica exacta de :class:`GoalsModel`.
    """

    proxy_weight: float = 0.0
    threat_to_goal: dict = field(default_factory=dict)
    creativity_to_assist: dict = field(default_factory=dict)

    def fit(self, df: pd.DataFrame) -> "EventProxyGoalsModel":
        super().fit(df)
        if not 0.0 <= self.proxy_weight <= 1.0:
            raise ValueError("proxy_weight debe estar en [0, 1]")

        d = df[pd.to_numeric(df.get("minutes"), errors="coerce").fillna(0) > 0].copy()
        d["pos"] = normaliza_posicion(d.get("position", pd.Series(index=d.index, dtype="object")))
        self.threat_to_goal = self._scales(d, "threat", "goals_scored")
        self.creativity_to_assist = self._scales(d, "creativity", "assists")
        self.metadata |= {
            "proxy_weight": float(self.proxy_weight),
            "threat_to_goal": self.threat_to_goal,
            "creativity_to_assist": self.creativity_to_assist,
        }
        return self

    @staticmethod
    def _scales(frame: pd.DataFrame, proxy: str, target: str) -> dict:
        p = pd.to_numeric(frame.get(proxy), errors="coerce")
        y = pd.to_numeric(frame.get(target), errors="coerce")
        valid = p.notna() & y.notna() & (p >= 0)
        global_den = float(p[valid].sum())
        global_scale = float(y[valid].sum() / global_den) if global_den > 100.0 else 0.0
        scales = {}
        for pos in POSICIONES:
            mask = valid & (frame["pos"] == pos)
            den = float(p[mask].sum())
            # Una posición con poco volumen hereda el mapeo global; nunca se
            # completa un dato ausente con cero observado.
            scales[pos] = float(y[mask].sum() / den) if den > 100.0 else global_scale
        return scales

    def rate(self, tasas: pd.DataFrame, posiciones: pd.Series, tipo: str) -> np.ndarray:
        base = super().rate(tasas, posiciones, tipo)
        if self.proxy_weight <= 0:
            return base

        if tipo == "gol":
            col, scales = "threat90", self.threat_to_goal
        else:
            col, scales = "creativity90", self.creativity_to_assist
        raw = pd.to_numeric(tasas.get(col), errors="coerce").to_numpy(dtype=float)
        scale = posiciones.map(lambda p: scales.get(p, 0.0)).to_numpy(dtype=float)
        proxy = raw * scale
        mixed = np.where(
            np.isfinite(proxy) & (proxy >= 0),
            (1.0 - self.proxy_weight) * base + self.proxy_weight * proxy,
            base,
        )
        return np.clip(mixed, 0.0, None)


def fit_temporal_fold(frame: pd.DataFrame, target_season: str, *, random_state: int = 42) -> dict:
    """Ajusta un par de modelos usando solo temporadas anteriores al objetivo.

    La última temporada disponible se reserva para calibración de minutos; no
    entra al clasificador base. Puntos aprende parámetros globales en todo el
    pasado y reconstruye estado individual causalmente en cada jornada.
    """
    seasons = sorted(str(s) for s in frame["season"].dropna().unique())
    if not seasons or any(s >= target_season for s in seasons):
        raise ValueError(f"fold no causal para {target_season}: {seasons[-3:]}")
    calibration = seasons[-1]
    minutes = MinutesModel(
        version=f"fold-{target_season}", random_state=random_state, calibrar=True
    ).fit(frame, calib_season=calibration)
    points = PointsModel(version=f"fold-{target_season}").fit(frame)
    return {
        "minutes": minutes,
        "points": points,
        "metadata": {
            "target_season": target_season,
            "train_seasons": seasons,
            "calibration_season": calibration,
            "rows": int(len(frame)),
        },
    }


def with_event_proxy(bundle: dict, frame: pd.DataFrame, weight: float) -> dict:
    """Clona un fold y cambia una sola variable: el peso de proxies de eventos."""
    out = copy.deepcopy(bundle)
    goals = EventProxyGoalsModel(
        peso_xg=out["points"].goals.peso_xg,
        k=out["points"].goals.k,
        proxy_weight=float(weight),
    ).fit(frame)
    out["points"].goals = goals
    out["metadata"] = {**out.get("metadata", {}), "event_proxy_weight": float(weight)}
    return out
