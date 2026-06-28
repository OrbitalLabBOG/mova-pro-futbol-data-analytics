"""Métricas de evaluación de pronósticos probabilísticos 1X2."""
from __future__ import annotations

import numpy as np

# Orden canónico de resultados: Home, Draw, Away.
ORDER = ("H", "D", "A")


def rps(probs, outcome_idx) -> float:
    """Ranked Probability Score (ordinal H/D/A), normalizado por (r-1). Menor mejor, [0,1].

    probs: array (n,3) ; outcome_idx: array (n,) con 0=H,1=D,2=A.
    """
    p = np.asarray(probs, dtype=float)
    e = np.zeros_like(p)
    e[np.arange(len(e)), np.asarray(outcome_idx)] = 1.0
    cp = np.cumsum(p, axis=1)[:, :-1]
    ce = np.cumsum(e, axis=1)[:, :-1]
    return float(np.mean(np.sum((cp - ce) ** 2, axis=1) / (p.shape[1] - 1)))


def brier(probs, outcome_idx) -> float:
    p = np.asarray(probs, dtype=float)
    e = np.zeros_like(p)
    e[np.arange(len(e)), np.asarray(outcome_idx)] = 1.0
    return float(np.mean(np.sum((p - e) ** 2, axis=1)))


def logloss(probs, outcome_idx, eps=1e-15) -> float:
    p = np.clip(np.asarray(probs, dtype=float), eps, 1.0)
    idx = np.asarray(outcome_idx)
    return float(-np.mean(np.log(p[np.arange(len(p)), idx])))


def skill_score(metric_model: float, metric_baseline: float) -> float:
    """1 - modelo/baseline. >0 = el modelo bate al baseline (mercado)."""
    if metric_baseline == 0:
        return 0.0
    return 1.0 - metric_model / metric_baseline
