"""Motor de partido: Elo-diff → goles esperados → Dixon-Coles → P(1X2).

Mapeo dr→λ calibrado sobre intl_results (Elo propio pre-partido + goles reales).
Dixon-Coles añade corrección ρ de marcadores bajos. Artefacto en models/dc/params.json.
"""
from __future__ import annotations

import json
import math

import numpy as np
from scipy.optimize import minimize_scalar
from scipy.stats import poisson

from .config import DC_DIR, MAX_GOALS

_PARAMS_PATH = DC_DIR / "params.json"


# ── Mapeo dr → (λ_home, λ_away) ────────────────────────────────────
def lambdas(dr: float, params: dict) -> tuple[float, float]:
    b0, b1 = params["b0"], params["b1"]
    lh = math.exp(b0 + b1 * dr / 100.0)
    la = math.exp(b0 - b1 * dr / 100.0)
    return lh, la


# ── Dixon-Coles ────────────────────────────────────────────────────
def _tau(x, y, lh, la, rho):
    if x == 0 and y == 0:
        return 1.0 - lh * la * rho
    if x == 0 and y == 1:
        return 1.0 + lh * rho
    if x == 1 and y == 0:
        return 1.0 + la * rho
    if x == 1 and y == 1:
        return 1.0 - rho
    return 1.0


def score_matrix(lh: float, la: float, rho: float, max_goals: int = MAX_GOALS) -> np.ndarray:
    ph = poisson.pmf(np.arange(max_goals + 1), lh)
    pa = poisson.pmf(np.arange(max_goals + 1), la)
    M = np.outer(ph, pa)
    for x in (0, 1):
        for y in (0, 1):
            M[x, y] *= _tau(x, y, lh, la, rho)
    return M / M.sum()


def p_1x2(M: np.ndarray) -> tuple[float, float, float]:
    home = float(np.tril(M, -1).sum())   # x>y
    draw = float(np.trace(M))
    away = float(np.triu(M, 1).sum())    # y>x
    return home, draw, away


def predict_1x2(dr: float, params: dict) -> tuple[float, float, float]:
    lh, la = lambdas(dr, params)
    return p_1x2(score_matrix(lh, la, params["rho"]))


# ── Calibración sobre histórico ────────────────────────────────────
def fit(conn, since="1990-01-01", rho_sample=8000) -> dict:
    """Ajusta b0,b1 (Poisson) y ρ (DC) sobre intl_results."""
    from sklearn.linear_model import PoissonRegressor

    rows = conn.execute(
        """SELECT home_score, away_score, neutral, home_elo_pre, away_elo_pre
           FROM intl_results WHERE match_date >= ? AND home_elo_pre IS NOT NULL""",
        (since,),
    ).fetchall()
    dr, goals = [], []
    matches = []
    for hs, as_, neutral, he, ae in rows:
        d = (he - ae) + (0 if neutral else 100)
        dr.append(d); goals.append(hs)          # perspectiva local
        dr.append(-d); goals.append(as_)        # perspectiva visitante
        matches.append((hs, as_, d))
    X = (np.array(dr) / 100.0).reshape(-1, 1)
    y = np.array(goals, dtype=float)
    pr = PoissonRegressor(alpha=1e-6, max_iter=500).fit(X, y)
    b0, b1 = float(pr.intercept_), float(pr.coef_[0])

    # ρ por MLE sobre una muestra de partidos
    sample = matches[-rho_sample:] if len(matches) > rho_sample else matches

    def negll(rho):
        ll = 0.0
        for hs, as_, d in sample:
            lh, la = lambdas(d, {"b0": b0, "b1": b1})
            if hs <= MAX_GOALS and as_ <= MAX_GOALS:
                p = score_matrix(lh, la, rho)[hs, as_]
                ll += math.log(max(p, 1e-12))
        return -ll

    rho = float(minimize_scalar(negll, bounds=(-0.2, 0.0), method="bounded").x)
    params = {"b0": b0, "b1": b1, "rho": rho, "since": since,
              "n_obs": len(matches), "avg_goals": math.exp(b0)}
    return params


def save(params: dict):
    DC_DIR.mkdir(parents=True, exist_ok=True)
    _PARAMS_PATH.write_text(json.dumps(params, indent=2))


def load() -> dict:
    return json.loads(_PARAMS_PATH.read_text())


def exists() -> bool:
    return _PARAMS_PATH.exists()
