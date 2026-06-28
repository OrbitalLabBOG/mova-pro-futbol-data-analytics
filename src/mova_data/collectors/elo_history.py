"""Histórico internacional (martj42) + Elo calculado por nosotros.

Fuente: github.com/martj42/international_results (1872→hoy, ~49K partidos, CC0-ish).
Calculamos un World Football Elo propio sobre todo el histórico → para cada partido
guardamos el Elo pre-partido (para calibrar dr→goles) y el rating actual por equipo
(para predicción). Self-consistente: el mismo Elo se usa en calibración y predicción.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import logging
import urllib.request

from ..teams import resolve

logger = logging.getLogger("mova.elo_history")
URL = "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"

# K por importancia del torneo (World Football Elo).
K_BY_TOURNAMENT = {
    "FIFA World Cup": 60,
    "FIFA World Cup qualification": 40,
    "Friendly": 20,
}
K_CONTINENTAL = 50   # Euro, Copa América, AFCON, etc. (championship)
K_DEFAULT = 30


def _k(tournament: str) -> int:
    if tournament in K_BY_TOURNAMENT:
        return K_BY_TOURNAMENT[tournament]
    t = (tournament or "").lower()
    if "qualification" in t:
        return 40
    if any(x in t for x in ("championship", "cup of nations", "copa américa",
                            "copa america", "euro", "uefa", "gold cup", "asian cup",
                            "nations league")):
        return K_CONTINENTAL
    return K_DEFAULT


def _g_multiplier(gd: int) -> float:
    gd = abs(gd)
    if gd <= 1:
        return 1.0
    if gd == 2:
        return 1.5
    return (11 + gd) / 8.0


def collect(conn) -> dict:
    raw = urllib.request.urlopen(
        urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"}), timeout=60
    ).read().decode()
    rows = list(csv.DictReader(io.StringIO(raw)))

    ratings: dict[str, float] = {}
    nmatch: dict[str, int] = {}
    last_date: dict[str, str] = {}
    BASE = 1500.0
    out_rows = []

    for r in rows:
        h, a = r["home_team"], r["away_team"]
        hs, as_ = r["home_score"], r["away_score"]
        if hs in ("", "NA", None) or as_ in ("", "NA", None):
            continue  # partido futuro / sin resultado
        try:
            hs, as_ = int(hs), int(as_)
        except ValueError:
            continue
        rh = ratings.get(h, BASE)
        ra = ratings.get(a, BASE)
        neutral = str(r.get("neutral", "")).upper() == "TRUE"
        dr = rh - ra + (0 if neutral else 100)
        we = 1.0 / (1.0 + 10 ** (-dr / 400.0))
        w = 1.0 if hs > as_ else (0.5 if hs == as_ else 0.0)
        k = _k(r["tournament"]) * _g_multiplier(hs - as_)
        delta = k * (w - we)

        out_rows.append((r["date"], h, a, hs, as_, r["tournament"],
                         int(neutral), round(rh, 2), round(ra, 2)))
        ratings[h] = rh + delta
        ratings[a] = ra - delta
        for t in (h, a):
            nmatch[t] = nmatch.get(t, 0) + 1
            last_date[t] = r["date"]

    # escribir intl_results
    conn.executemany(
        """INSERT OR REPLACE INTO intl_results
           (source, match_date, home_team, away_team, home_score, away_score,
            tournament, neutral, home_elo_pre, away_elo_pre)
           VALUES ('martj42',?,?,?,?,?,?,?,?,?)""",
        out_rows,
    )
    # escribir elo_computed (rating actual por equipo, resuelto a canónico)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    conn.execute("DELETE FROM elo_computed")
    conn.executemany(
        """INSERT OR REPLACE INTO elo_computed
           (team_raw, team, rating, n_matches, last_date, computed_at)
           VALUES (?,?,?,?,?,?)""",
        [(t, resolve(conn, t), round(ratings[t], 2), nmatch[t], last_date[t], now)
         for t in ratings],
    )
    conn.commit()
    wc = conn.execute("SELECT count(*) FROM elo_computed WHERE team IS NOT NULL").fetchone()[0]
    logger.info("intl_results: %d partidos | elo_computed: %d equipos (%d→canónico)",
                len(out_rows), len(ratings), wc)
    return {"matches": len(out_rows), "teams": len(ratings), "mapped": wc}
