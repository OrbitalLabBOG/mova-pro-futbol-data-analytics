"""ESPN — fixtures + odds DraftKings del Mundial (sin auth).

scoreboard?dates=YYYYMMDD-YYYYMMDD → events con competitors, status y odds
(moneyline american como string, puede ser 'OFF'). Complementa WhoScored con
odds de casa y fixtures futuros antes de jugarse.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import urllib.request

logger = logging.getLogger("mova.espn")
URL = ("https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/"
       "scoreboard?dates={start}-{end}&limit=200")


def _ml(x):
    """american odds string ('+8000', '-115', 'OFF') → int o None."""
    try:
        return int(str(x).replace("+", ""))
    except (TypeError, ValueError):
        return None


def _side_ml(ml: dict, side: str):
    """moneyline[side].current.odds (o .close) de forma defensiva (puede ser None)."""
    s = ml.get(side)
    if not isinstance(s, dict):
        return None
    cur = s.get("current") or s.get("close") or s.get("open") or {}
    return _ml(cur.get("odds")) if isinstance(cur, dict) else None


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def collect(conn, start="20260611", end="20260720") -> dict:
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    j = _get(URL.format(start=start, end=end))
    evs = j.get("events", [])
    n = 0
    for e in evs:
        comp = e["competitions"][0]
        home = away = None
        for c in comp["competitors"]:
            side = {"id": c["id"], "team": c["team"].get("displayName"),
                    "score": c.get("score")}
            if c["homeAway"] == "home":
                home = side
            else:
                away = side
        if not home or not away:
            continue
        mlh = mld = mla = None
        odds = [o for o in (comp.get("odds") or []) if isinstance(o, dict)]
        if odds:
            ml = odds[0].get("moneyline") or {}
            mlh, mld, mla = _side_ml(ml, "home"), _side_ml(ml, "draw"), _side_ml(ml, "away")
        conn.execute(
            """INSERT OR REPLACE INTO espn_fixtures
               (espn_id, date_utc, status, home_team, away_team, home_score,
                away_score, ml_home, ml_draw, ml_away, venue, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (int(e["id"]), e.get("date"),
             e["status"]["type"]["name"], home["team"], away["team"],
             _ml(home["score"]), _ml(away["score"]), mlh, mld, mla,
             (comp.get("venue") or {}).get("fullName"), now),
        )
        n += 1
    conn.commit()
    logger.info("ESPN: %d fixtures (con odds DraftKings)", n)
    return {"rows": n}
