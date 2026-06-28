"""Kalshi — mercados del Mundial (probabilidad real, dinero). Sin auth de lectura.

Serie ganador `KXMENWORLDCUP`: 1 mercado por selección. Precios en campos
`*_dollars` y como STRING (0-1 = prob. implícita). Guardamos snapshot con
timestamp para construir serie temporal de probabilidades.
"""
from __future__ import annotations

import datetime as dt
import logging
import urllib.request
import json

logger = logging.getLogger("mova.kalshi")
BASE = "https://api.elections.kalshi.com/trade-api/v2"
WINNER_SERIES = "KXMENWORLDCUP"


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def collect(conn, series=WINNER_SERIES, market_type="winner") -> dict:
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    j = _get(f"{BASE}/markets?series_ticker={series}&status=open&limit=200")
    ms = j.get("markets", [])
    n = 0
    for m in ms:
        entity = m.get("yes_sub_title") or m.get("title")
        last = _f(m.get("last_price_dollars"))
        bid = _f(m.get("yes_bid_dollars"))
        ask = _f(m.get("yes_ask_dollars"))
        prob = last if last is not None else (
            (bid + ask) / 2 if bid is not None and ask is not None else None)
        conn.execute(
            """INSERT OR REPLACE INTO market_odds
               (source, captured_at, market_type, entity, prob, yes_bid, yes_ask,
                last_price, ticker)
               VALUES ('kalshi', ?, ?, ?, ?, ?, ?, ?, ?)""",
            (now, market_type, entity, prob, bid, ask, last, m.get("ticker")),
        )
        n += 1
    conn.commit()
    logger.info("Kalshi %s: %d mercados (snapshot %s)", series, n, now)
    return {"rows": n, "captured_at": now}
