"""Contexto de odds pre-deadline para la variante defensiva en shadow."""

from __future__ import annotations

import copy
import re
import unicodedata

import numpy as np
import pandas as pd
from scipy.optimize import least_squares
from scipy.stats import poisson

from mova_fpl.models.points import PointsModel

MARKET_WEIGHT = 0.95  # seleccionado antes de holdout en el experimento versionado

_ALIASES = {
    "man city": "manchester city", "man utd": "manchester united",
    "man united": "manchester united", "spurs": "tottenham hotspur",
    "tottenham": "tottenham hotspur", "wolves": "wolverhampton wanderers",
    "wolverhampton": "wolverhampton wanderers", "nott m forest": "nottingham forest",
    "newcastle": "newcastle united", "west ham": "west ham united",
    "brighton": "brighton and hove albion",
    "leeds": "leeds united",
}


def canonical_team(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode().lower()
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    return _ALIASES.get(text, text)


def _devig(values) -> np.ndarray:
    inverse = 1.0 / np.asarray(values, dtype=float)
    return inverse / inverse.sum()


def _score_probabilities(home: float, away: float, max_goals: int = 12) -> np.ndarray:
    goals = np.arange(max_goals + 1)
    matrix = np.outer(poisson.pmf(goals, home), poisson.pmf(goals, away))
    one_x_two = np.array([np.tril(matrix, -1).sum(), np.trace(matrix),
                          np.triu(matrix, 1).sum()])
    one_x_two /= one_x_two.sum()
    over = 1.0 - poisson.cdf(2, home + away)
    return np.r_[one_x_two, over]


def infer_lambdas(p_1x2, p_over_25: float) -> tuple[float, float, float]:
    target = np.asarray(p_1x2, dtype=float)
    tilt = float(np.clip(target[0] - target[2], -.8, .8))
    x0 = np.array([2.7 * (.5 + .32 * tilt), 2.7 * (.5 - .32 * tilt)])

    def residual(x):
        predicted = _score_probabilities(float(x[0]), float(x[1]))
        return np.r_[predicted[:3] - target, predicted[3] - p_over_25]

    fit = least_squares(residual, np.clip(x0, .2, 4.5), bounds=(.05, 5.5),
                        xtol=1e-10, ftol=1e-10)
    return float(fit.x[0]), float(fit.x[1]), float(np.sqrt(np.mean(residual(fit.x) ** 2)))


def build_context(fixtures: list[dict], odds_rows: list[dict]) -> tuple[list[dict], dict]:
    """Consenso devigged por bookmaker, unido a fixtures sin usar resultados."""
    events: dict[str, list[dict]] = {}
    for row in odds_rows:
        events.setdefault(str(row["provider_event_id"]), []).append(row)
    contexts = []
    for event_rows in events.values():
        sample = event_rows[0]
        books: dict[str, list[dict]] = {}
        for row in event_rows:
            books.setdefault(str(row["bookmaker_key"]), []).append(row)
        one_x_two, totals = [], []
        for rows in books.values():
            h2h = {canonical_team(item["outcome_name"]): float(item["price"])
                   for item in rows if item["market_key"] == "h2h"}
            home = canonical_team(sample["home_team"])
            away = canonical_team(sample["away_team"])
            draw = h2h.get("draw")
            if home in h2h and away in h2h and draw:
                one_x_two.append(_devig([h2h[home], draw, h2h[away]]))
            line = {str(item["outcome_name"]).lower(): float(item["price"])
                    for item in rows if item["market_key"] == "totals"
                    and item.get("point") is not None and abs(float(item["point"]) - 2.5) < .01}
            if "over" in line and "under" in line:
                totals.append(_devig([line["over"], line["under"]])[0])
        if not one_x_two or not totals:
            continue
        p = np.mean(one_x_two, axis=0)
        lam_h, lam_a, fit = infer_lambdas(p, float(np.mean(totals)))
        kickoff = pd.Timestamp(sample["commence_time"])
        candidates = [fixture for fixture in fixtures
                      if abs((pd.Timestamp(fixture["kickoff_time"]) - kickoff).total_seconds()) <= 300
                      and canonical_team(fixture["home_team"]) == canonical_team(sample["home_team"])
                      and canonical_team(fixture["away_team"]) == canonical_team(sample["away_team"])]
        if len(candidates) != 1:
            continue
        contexts.append({"fixture": int(candidates[0]["fixture"]),
                         "lambda_home": lam_h, "lambda_away": lam_a,
                         "fit_rmse": fit, "bookmakers": len(one_x_two)})
    quality = {"fixtures": len(fixtures), "covered": len(contexts),
               "coverage_ratio": len(contexts) / len(fixtures) if fixtures else 0.0,
               "minimum_bookmakers": min((row["bookmakers"] for row in contexts), default=0),
               "max_fit_rmse": max((row["fit_rmse"] for row in contexts), default=None)}
    return contexts, quality


class MarketDefensePointsModel(PointsModel):
    """Reemplaza sólo lambda concedida; ataque y tasas individuales quedan intactos."""

    def __init__(self, base: PointsModel, context: list[dict], weight: float = MARKET_WEIGHT):
        self.__dict__ = copy.deepcopy(base.__dict__)
        self._market_weight = float(weight)
        self._market_context = {int(row["fixture"]): (float(row["lambda_home"]),
                                                       float(row["lambda_away"]))
                                for row in context}

    def _contexto_partido(self, roster, fuerza, equipos=None):
        multiplier, conceded = super()._contexto_partido(roster, fuerza, equipos)
        work = roster.reset_index(drop=True)
        fixtures = pd.to_numeric(work.get("fixture"), errors="coerce")
        homes = pd.to_numeric(work.get("was_home"), errors="coerce") == 1
        updated = conceded.copy()
        for fixture, (lambda_home, lambda_away) in self._market_context.items():
            in_fixture = fixtures == fixture
            home_mask = (in_fixture & homes).to_numpy()
            away_mask = (in_fixture & ~homes).to_numpy()
            updated[home_mask] = ((1 - self._market_weight) * conceded[home_mask]
                                  + self._market_weight * lambda_away)
            updated[away_mask] = ((1 - self._market_weight) * conceded[away_mask]
                                  + self._market_weight * lambda_home)
        return multiplier, np.clip(updated, .05, 5.5)
