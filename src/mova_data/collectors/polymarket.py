"""Polymarket — mercado descentralizado del ganador del Mundial (Gamma API, sin auth).

Va a la misma tabla genérica `market_odds` (source='polymarket'). Gamma devuelve
`outcomes`/`outcomePrices` como STRING JSON; `outcomePrices[0]` = prob. del 'Yes'
(probabilidad implícita 0-1). El nombre del equipo está en `groupItemTitle`.
NOTA: la CLOB API (clob.polymarket.com) da connection reset desde WSL; Gamma sí
responde y trae precios (bestBid/bestAsk/lastTradePrice).
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
import time

import cloudscraper

logger = logging.getLogger("mova.polymarket")
EVENT_SLUG = "world-cup-winner"
GAMMA = "https://gamma-api.polymarket.com/events?slug={slug}"
_scraper = None


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _team(m: dict) -> str | None:
    t = m.get("groupItemTitle")
    if t:
        return t
    q = m.get("question") or ""
    mt = re.search(r"Will (.+?) win", q)
    return mt.group(1) if mt else q or None


def _get(url, retries=4):
    """Gamma API es intermitente desde WSL (connection reset). CloudScraper + reintentos."""
    global _scraper
    if _scraper is None:
        _scraper = cloudscraper.create_scraper()
    last = None
    for i in range(retries):
        try:
            r = _scraper.get(url, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
    raise last


def collect(conn, slug=EVENT_SLUG, market_type="winner") -> dict:
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    events = _get(GAMMA.format(slug=slug))
    if not events:
        logger.warning("Polymarket: slug '%s' sin eventos", slug)
        return {"rows": 0}
    markets = events[0].get("markets", [])
    n = 0
    for m in markets:
        entity = _team(m)
        try:
            prices = json.loads(m.get("outcomePrices", "[]"))
        except (TypeError, json.JSONDecodeError):
            prices = []
        prob = _f(prices[0]) if prices else _f(m.get("lastTradePrice"))
        conn.execute(
            """INSERT OR REPLACE INTO market_odds
               (source, captured_at, market_type, entity, prob, yes_bid, yes_ask,
                last_price, ticker)
               VALUES ('polymarket', ?, ?, ?, ?, ?, ?, ?, ?)""",
            (now, market_type, entity, prob, _f(m.get("bestBid")), _f(m.get("bestAsk")),
             _f(m.get("lastTradePrice")), m.get("slug") or m.get("conditionId")),
        )
        n += 1
    conn.commit()
    logger.info("Polymarket %s: %d mercados (snapshot %s)", slug, n, now)
    return {"rows": n, "captured_at": now}
