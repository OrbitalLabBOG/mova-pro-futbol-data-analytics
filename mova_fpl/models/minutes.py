"""Modelo de minutos: P(0) / P(1-59) / P(60+) por jugador y partido.

Es el driver dominante del xP. Un jugador que no juega vale cero por muy bueno
que sea, y es donde mas se equivocan los modelos ingenuos.

Se evalua por CALIBRACION, no por accuracy: al optimizador no le sirve un
clasificador que acierta la clase modal, le sirve una probabilidad que
corresponda a la frecuencia real.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.frozen import FrozenEstimator
from sklearn.ensemble import HistGradientBoostingClassifier

from mova_fpl.models.features.minutes_features import FEATURES, build, matrix

CLASES = (0, 1, 2)          # 0 min · 1-59 · 60+
NOMBRE = "minutes"
VERSION = "1.0.0"


def expected_calibration_error(y_true, p_pred, bins: int = 10) -> float:
    """ECE con bins de igual ancho sobre [0,1]."""
    y_true = np.asarray(y_true, dtype=float)
    p_pred = np.asarray(p_pred, dtype=float)
    bordes = np.linspace(0.0, 1.0, bins + 1)
    idx = np.clip(np.digitize(p_pred, bordes[1:-1], right=False), 0, bins - 1)
    ece = 0.0
    for b in range(bins):
        m = idx == b
        if not m.any():
            continue
        ece += m.mean() * abs(p_pred[m].mean() - y_true[m].mean())
    return float(ece)


def calibration_table(y_true, p_pred, bins: int = 10) -> pd.DataFrame:
    y_true = np.asarray(y_true, dtype=float)
    p_pred = np.asarray(p_pred, dtype=float)
    bordes = np.linspace(0.0, 1.0, bins + 1)
    idx = np.clip(np.digitize(p_pred, bordes[1:-1], right=False), 0, bins - 1)
    filas = []
    for b in range(bins):
        m = idx == b
        filas.append({"bin": f"{bordes[b]:.1f}-{bordes[b+1]:.1f}", "n": int(m.sum()),
                      "predicho": float(p_pred[m].mean()) if m.any() else np.nan,
                      "observado": float(y_true[m].mean()) if m.any() else np.nan})
    return pd.DataFrame(filas)


def brier(y_true, p_pred) -> float:
    return float(np.mean((np.asarray(p_pred, dtype=float) - np.asarray(y_true, dtype=float)) ** 2))


@dataclass
class MinutesModel:
    """Clasificador multiclase con calibracion isotonica sobre una ventana temporal."""
    name: str = NOMBRE
    version: str = VERSION
    max_iter: int = 300
    learning_rate: float = 0.06
    random_state: int = 42
    calibrar: bool = True
    _modelo: object = field(default=None, repr=False)
    metadata: dict = field(default_factory=dict)

    def fit(self, df: pd.DataFrame, calib_season: str | None = None) -> "MinutesModel":
        """Entrena. `calib_season` se reserva para calibrar y no entra al ajuste base.

        La separacion es TEMPORAL, no aleatoria: calibrar con filas mezcladas del
        mismo periodo infla la calidad aparente.
        """
        d = build(df)
        base = HistGradientBoostingClassifier(
            max_iter=self.max_iter, learning_rate=self.learning_rate,
            random_state=self.random_state, early_stopping=False)

        if self.calibrar and calib_season and (d["season"] == calib_season).any():
            ajuste = d[d["season"] != calib_season]
            calib = d[d["season"] == calib_season]
            Xa, ya = matrix(ajuste)
            base.fit(Xa, ya)
            Xc, yc = matrix(calib)
            cal = CalibratedClassifierCV(FrozenEstimator(base), method="isotonic")
            cal.fit(Xc, yc)
            self._modelo = cal
            self.metadata = {"filas_ajuste": len(Xa), "filas_calibracion": len(Xc),
                             "calib_season": calib_season}
        else:
            X, y = matrix(d)
            base.fit(X, y)
            self._modelo = base
            self.metadata = {"filas_ajuste": len(X), "filas_calibracion": 0,
                             "calib_season": None}

        self.metadata |= {"features": list(FEATURES), "temporadas": sorted(d["season"].unique())}
        return self

    def predict_proba_built(self, d: pd.DataFrame) -> np.ndarray:
        """Como predict_proba pero sobre un frame ya pasado por build().

        Construir las features es lo caro del ciclo; en el backtest se hace una
        sola vez por jornada y se reutiliza.
        """
        if self._modelo is None:
            raise RuntimeError("el modelo no ha sido entrenado")
        X, _ = matrix(d)
        return self._normalizar(self._modelo.predict_proba(X), len(X))

    def _normalizar(self, p: np.ndarray, n: int) -> np.ndarray:
        clases = list(getattr(self._modelo, "classes_", CLASES))
        salida = np.zeros((n, 3), dtype=float)
        for i, c in enumerate(clases):
            salida[:, int(c)] = p[:, i]
        s = salida.sum(axis=1, keepdims=True)
        return salida / np.where(s == 0, 1.0, s)

    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        if self._modelo is None:
            raise RuntimeError("el modelo no ha sido entrenado")
        X, _ = matrix(build(df))
        return self._normalizar(self._modelo.predict_proba(X), len(X))

    def p60(self, df: pd.DataFrame) -> np.ndarray:
        return self.predict_proba(df)[:, 2]

    def evaluate(self, df: pd.DataFrame, bins: int = 10) -> dict:
        """Calibracion y Brier frente al baseline de frecuencia historica."""
        d = build(df)
        X, y = matrix(d)
        p = self.predict_proba(df)
        y60 = (y.to_numpy() == 2).astype(float)
        p60 = p[:, 2]

        # baseline: la tasa historica del propio jugador. Sin historial, la base global.
        base = d["tasa_60"].to_numpy(dtype=float)
        base = np.where(np.isnan(base), np.nanmean(y60), base)

        return {
            "n": int(len(y)),
            "ece_p60": expected_calibration_error(y60, p60, bins),
            "ece_p60_baseline": expected_calibration_error(y60, base, bins),
            "brier_p60": brier(y60, p60),
            "brier_p60_baseline": brier(y60, base),
            "log_loss_3c": float(-np.mean(np.log(np.clip(
                p[np.arange(len(y)), y.to_numpy()], 1e-12, None)))),
            "tabla_calibracion": calibration_table(y60, p60, bins),
        }
