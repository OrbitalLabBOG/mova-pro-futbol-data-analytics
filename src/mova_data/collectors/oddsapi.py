"""The Odds API — odds multi-casa del Mundial (consenso + Pinnacle/Betfair).

Plan free 500 créditos/mes; 1 crédito = 1 región × 1 mercado. Guarda TODAS las
casas en `odds_quotes` (granular) y un consenso del ganador en `market_odds`.
Loguea créditos restantes (header x-requests-remaining) para no pasarnos.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import statistics
import urllib.request
from pathlib import Path

from ..config import ODDS_API_KEY, RAW_DIR

logger = logging.getLogger("mova.oddsapi")
BASE = "https://api.the-odds-api.com/v4"
RAW = RAW_DIR / "oddsapi"


def _get(path):
    url = f"{BASE}{path}{'&' if '?' in path else '?'}apiKey={ODDS_API_KEY}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    r = urllib.request.urlopen(req, timeout=40)
    remaining = r.headers.get("x-requests-remaining")
    return json.load(r), remaining


def _insert_quotes(conn, now, scope, events):
    n = 0
    for e in events:
        for bk in e.get("bookmakers", []):
            for mk in bk.get("markets", []):
                for oc in mk.get("outcomes", []):
                    conn.execute(
                        """INSERT OR REPLACE INTO odds_quotes
                           (source, captured_at, scope, event_id, commence_time,
                            home_team, away_team, bookmaker, market, outcome, price, point)
                           VALUES ('oddsapi',?,?,?,?,?,?,?,?,?,?,?)""",
                        (now, scope, e.get("id"), e.get("commence_time"),
                         e.get("home_team"), e.get("away_team"), bk.get("key"),
                         mk.get("key"), oc.get("name"), oc.get("price"),
                         oc.get("point") if oc.get("point") is not None else 0),
                    )
                    n += 1
    return n


def collect(conn, regions="eu", winner=True, match=True,
            markets="h2h,totals,spreads") -> dict:
    if not ODDS_API_KEY:
        logger.error("ODDS_API_KEY no configurada (.env.local)"); return {"error": "no_key"}
    RAW.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    out = {"quotes": 0}

    if winner:
        j, rem = _get(f"/sports/soccer_fifa_world_cup_winner/odds?regions={regions}"
                      f"&markets=outrights&oddsFormat=decimal")
        (RAW / "winner_latest.json").write_text(json.dumps(j))
        out["quotes"] += _insert_quotes(conn, now, "winner", j)
        # consenso → market_odds (mediana de 1/price entre casas)
        by_team: dict[str, list[float]] = {}
        for e in j:
            for bk in e.get("bookmakers", []):
                for mk in bk.get("markets", []):
                    for oc in mk.get("outcomes", []):
                        if oc.get("price"):
                            by_team.setdefault(oc["name"], []).append(1 / oc["price"])
        for team, probs in by_team.items():
            conn.execute(
                """INSERT OR REPLACE INTO market_odds
                   (source, captured_at, market_type, entity, prob, last_price)
                   VALUES ('oddsapi', ?, 'winner', ?, ?, NULL)""",
                (now, team, statistics.median(probs)),
            )
        logger.info("OddsAPI winner: %d casas-cuotas, %d equipos (rem=%s)",
                    out["quotes"], len(by_team), rem)

    if match:
        j, rem = _get(f"/sports/soccer_fifa_world_cup/odds?regions={regions}"
                      f"&markets={markets}&oddsFormat=decimal")
        (RAW / "match_latest.json").write_text(json.dumps(j))
        m = _insert_quotes(conn, now, "match", j)
        out["quotes"] += m
        logger.info("OddsAPI match: %d partidos, %d cuotas (rem=%s)", len(j), m, rem)
        out["credits_remaining"] = rem

    conn.commit()
    out["captured_at"] = now
    return out
