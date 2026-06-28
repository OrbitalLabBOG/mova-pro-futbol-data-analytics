"""Ratings Elo (propios, calculados) y diferencia de rating por partido."""
from __future__ import annotations

from .config import HOME_ADV_ELO


def get_ratings(conn) -> dict:
    """team canónico → Elo propio (elo_computed)."""
    return {t: r for t, r in conn.execute(
        "SELECT team, rating FROM elo_computed WHERE team IS NOT NULL")}


def get_ranks(conn) -> dict:
    rows = sorted(get_ratings(conn).items(), key=lambda x: -x[1])
    return {t: i + 1 for i, (t, _) in enumerate(rows)}


def dr(rating_home: float, rating_away: float, neutral: bool = True) -> float:
    """Diferencia de rating efectiva (con localía salvo neutral)."""
    return (rating_home - rating_away) + (0.0 if neutral else HOME_ADV_ELO)
