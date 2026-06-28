"""Modelo xG propio: regresión logística calibrada. Entrenar-una-vez, persistir en models/.

Penales fuera del fit (xg = PEN_XG constante). Lo que importa es la CALIBRACIÓN
(al agregar a nivel equipo el sesgo se acumula), no el AUC.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json

import joblib
import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression

from .config import XG_DIR, PEN_XG
from . import shots

_MODEL_PATH = XG_DIR / "model.joblib"
_META_PATH = XG_DIR / "meta.json"


def train(df, calibrate=True):
    """Entrena sobre tiros (excluye penales). Devuelve (modelo, meta)."""
    fit = df[df["play_type"] != "penalty"].copy()
    X = shots.design_matrix(fit)
    y = fit["is_goal"].to_numpy(dtype=int)
    base = LogisticRegression(max_iter=2000, C=1.0)
    model = CalibratedClassifierCV(base, method="isotonic", cv=5) if calibrate else base
    model.fit(X, y)
    meta = {
        "features": shots.FEATURES, "n_train": int(len(fit)),
        "n_goals": int(y.sum()), "calibrated": calibrate,
        "trained_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    return model, meta


def save(model, meta):
    XG_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, _MODEL_PATH)
    version = hashlib.sha1(open(_MODEL_PATH, "rb").read()).hexdigest()[:12]
    meta["version"] = version
    _META_PATH.write_text(json.dumps(meta, indent=2))
    return version


def load():
    return joblib.load(_MODEL_PATH), json.loads(_META_PATH.read_text())


def exists() -> bool:
    return _MODEL_PATH.exists()


def predict(model, df) -> np.ndarray:
    """xG por tiro. Penales = PEN_XG constante; resto = modelo calibrado."""
    X = shots.design_matrix(df)
    xg = model.predict_proba(X)[:, 1]
    pen = (df["play_type"] == "penalty").to_numpy()
    xg = np.where(pen, PEN_XG, xg)
    return xg
