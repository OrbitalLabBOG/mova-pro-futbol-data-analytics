"""Probabilidades de mercado: devigging (Power) + consenso.

- p_market_1x2: por partido, desde odds_quotes (h2h, múltiples casas) devigueado.
- p_market_winner: consenso de campeón desde market_odds (Kalshi+Polymarket+OddsAPI),
  ya casi limpios (mercados de predicción) → log-pool + renormalizar.
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import brentq

from mova_data.teams import resolve


def devig_power(odds: list[float]) -> np.ndarray:
    """Quita el margen con el método Power (corrige favorite-longshot bias)."""
    r = 1.0 / np.asarray(odds, dtype=float)
    if r.sum() <= 1.0:                      # sin overround (exchange/pred-market)
        return r / r.sum()
    f = lambda k: np.sum(r ** (1.0 / k)) - 1.0
    try:
        k = brentq(f, 0.5, 5.0)
        p = r ** (1.0 / k)
    except ValueError:
        p = r                               # fallback proporcional
    return p / p.sum()


def p_market_1x2(conn, oddsapi_event_id: str) -> tuple | None:
    """(pH,pD,pA) consenso devigueado entre casas para un partido. None si no hay h2h."""
    if not oddsapi_event_id:
        return None
    rows = conn.execute(
        """SELECT bookmaker, home_team, away_team, outcome, price
           FROM odds_quotes
           WHERE scope='match' AND market='h2h' AND event_id=?
             AND captured_at=(SELECT max(captured_at) FROM odds_quotes
                              WHERE scope='match' AND event_id=?)""",
        (oddsapi_event_id, oddsapi_event_id),
    ).fetchall()
    if not rows:
        return None
    home = rows[0][1]
    by_book: dict[str, dict] = {}
    for bk, h, a, outcome, price in rows:
        d = by_book.setdefault(bk, {})
        if outcome == h:
            d["H"] = price
        elif outcome == a:
            d["A"] = price
        elif outcome and outcome.lower() == "draw":
            d["D"] = price
    probs = []
    for d in by_book.values():
        if all(k in d for k in ("H", "D", "A")):
            probs.append(devig_power([d["H"], d["D"], d["A"]]))
    if not probs:
        return None
    return tuple(np.mean(probs, axis=0))    # consenso entre casas


def p_market_winner(conn) -> dict:
    """team canónico → prob. de campeón (consenso de mercados, renormalizado)."""
    rows = conn.execute(
        """SELECT source, entity, prob FROM market_odds mo
           WHERE market_type='winner' AND prob IS NOT NULL
             AND captured_at=(SELECT max(captured_at) FROM market_odds m2
                              WHERE m2.source=mo.source AND m2.market_type='winner')"""
    ).fetchall()
    agg: dict[str, list] = {}
    for source, entity, prob in rows:
        team = resolve(conn, entity)
        if team:
            agg.setdefault(team, []).append(prob)
    cons = {t: float(np.mean(v)) for t, v in agg.items()}
    s = sum(cons.values())
    return {t: p / s for t, p in cons.items()} if s > 0 else cons
