#!/usr/bin/env python3
"""Medición EN VIVO de microestructura — mercados del Mundial en Polymarket + Kalshi.

Mide lo que decide la viabilidad de market making / arbitraje:
  - spread bid/ask y profundidad real del order book por mercado,
  - overround del mercado de 48 equipos (¿hay sell-all / dutch arb?),
  - parámetros de liquidity rewards activos (rewardsMaxSpread/MinSize),
  - gap cross-venue Polymarket vs Kalshi (¿arbitraje?).

Requiere salir del sandbox (Cloudflare). Usa curl_cffi impersonate=chrome131.
Uso: python scripts/poly_microstructure.py
"""
import json
import statistics as st
import time

from curl_cffi import requests as creq

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
KALSHI = "https://external-api.kalshi.com/trade-api/v2"
IMPS = ["chrome131", "chrome124", "chrome120", "chrome116"]


def gget(url, tries=6, **kw):
    """GET con reintentos + rotación de huella TLS (Cloudflare resetea ráfagas)."""
    last = None
    for i in range(tries):
        try:
            r = creq.get(url, impersonate=IMPS[i % len(IMPS)], timeout=30, **kw)
            if r.status_code == 200:
                return r
            last = r
        except Exception as e:                       # noqa: BLE001
            last = e
        time.sleep(1.5 * (i + 1))
    return last if hasattr(last, "status_code") else _Dead()


class _Dead:
    status_code = 0
    def json(self):
        return {}


def poly_wc_winner():
    """Sub-mercados binarios 'Will X win the 2026 FIFA World Cup?'."""
    out = []
    for off in (0, 100, 200, 300, 400, 500, 600, 700, 800, 900, 1000, 1100):
        r = gget(f"{GAMMA}/markets?closed=false&limit=100&offset={off}")
        if getattr(r, "status_code", 0) != 200:
            continue
        ms = r.json()
        if not ms:
            break
        for m in ms:
            q = (m.get("question") or "")
            if "win the 2026 fifa world cup" in q.lower():
                out.append(m)
        time.sleep(0.4)
    return out


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def main():
    print("=" * 64)
    print("  MICROESTRUCTURA EN VIVO — Mundial 2026 (Polymarket + Kalshi)")
    print("=" * 64)

    wc = poly_wc_winner()
    print(f"\n[Polymarket] sub-mercados 'winner': {len(wc)}")
    rows = []
    for m in wc:
        try:
            prices = json.loads(m.get("outcomePrices") or "[]")
        except Exception:
            prices = []
        bb, ba = f(m.get("bestBid")), f(m.get("bestAsk"))
        yes = f(prices[0]) if prices else None
        rows.append({
            "team": (m.get("question") or "").replace("Will ", "").replace(
                " win the 2026 FIFA World Cup?", "").strip(),
            "yes": yes, "bid": bb, "ask": ba,
            "spread": (ba - bb) if (bb is not None and ba is not None) else None,
            "rmax": f(m.get("rewardsMaxSpread")), "rmin": f(m.get("rewardsMinSize")),
            "liq": f(m.get("liquidityNum") or m.get("liquidity")),
            "vol": f(m.get("volumeNum") or m.get("volume")),
            "tok": json.loads(m.get("clobTokenIds") or "[]"),
        })
    rows.sort(key=lambda r: -(r["yes"] or 0))

    print(f"\n  {'equipo':18} {'YES':>6} {'bid':>6} {'ask':>6} {'spread':>7} "
          f"{'rwdMaxSp':>8} {'liquidez':>10}")
    sum_ask = sum_bid = 0.0
    spreads, rewarded = [], 0
    for r in rows:
        if r["yes"] is None:
            continue
        sp = f"{r['spread']:.3f}" if r["spread"] is not None else "—"
        rmax = f"{r['rmax']:.3f}" if r["rmax"] else "—"
        if r["rmax"]:
            rewarded += 1
        if r["spread"] is not None:
            spreads.append(r["spread"])
        if r["ask"]:
            sum_ask += r["ask"]
        if r["bid"]:
            sum_bid += r["bid"]
        if r["yes"] >= 0.02 or (r["spread"] and r["spread"] > 0.03):
            print(f"  {r['team'][:18]:18} {r['yes']:6.3f} "
                  f"{(r['bid'] or 0):6.3f} {(r['ask'] or 0):6.3f} {sp:>7} "
                  f"{rmax:>8} {(r['liq'] or 0):10,.0f}")

    print(f"\n  --- Estructura del mercado de {len(rows)} equipos ---")
    print(f"  Σ asks (comprar TODOS los YES) = {sum_ask:.3f}  "
          f"-> {'ARB sell-all' if sum_ask>1.02 else 'sin arb claro'} "
          f"(overround {(sum_ask-1)*100:+.1f}%)")
    print(f"  Σ bids (vender TODOS los YES)  = {sum_bid:.3f}  "
          f"(si >1.0 habría arb comprando NO de todos)")
    if spreads:
        print(f"  spread bid/ask: mediana {st.median(spreads)*100:.1f}¢ | "
              f"min {min(spreads)*100:.1f}¢ | max {max(spreads)*100:.1f}¢")
    print(f"  mercados con liquidity rewards activos (rewardsMaxSpread>0): "
          f"{rewarded}/{len(rows)}")

    # Profundidad real del order book (CLOB) para top-3 equipos
    print("\n  --- Profundidad real (CLOB /book) top-3 favoritos ---")
    for r in rows[:3]:
        if not r["tok"]:
            continue
        rb = gget(f"{CLOB}/book?token_id={r['tok'][0]}")
        if rb.status_code != 200:
            print(f"  {r['team']}: book HTTP {rb.status_code}")
            continue
        b = rb.json()
        bids, asks = b.get("bids", []), b.get("asks", [])
        topbid = max((f(x["price"]) for x in bids), default=None)
        topask = min((f(x["price"]) for x in asks), default=None)
        depth_bid = sum(f(x["price"]) * f(x["size"]) for x in bids)
        depth_ask = sum(f(x["price"]) * f(x["size"]) for x in asks)
        sp = (topask - topbid) if topbid and topask else None
        print(f"  {r['team'][:18]:18} bid {topbid} / ask {topask} "
              f"(spread {sp*100:.1f}¢) | $ en libro: bids ${depth_bid:,.0f} asks ${depth_ask:,.0f} "
              f"| niveles {len(bids)}/{len(asks)}")

    # Contraste: ¿hay mercados WC con spread ANCHO (thin = única posible "room")?
    print("\n  --- Distribución de spreads en TODOS los mercados WC (thin vs efficient) ---")
    allwc = []
    for off in (0, 100, 200, 300, 400, 500):
        r = gget(f"{GAMMA}/markets?closed=false&limit=100&offset={off}")
        if getattr(r, "status_code", 0) != 200:
            continue
        for m in r.json():
            q = (m.get("question") or "").lower()
            if "world cup" in q or "fifa" in q:
                bb, ba = f(m.get("bestBid")), f(m.get("bestAsk"))
                if bb is not None and ba is not None and ba > bb:
                    allwc.append((ba - bb, m.get("question"), f(m.get("liquidityNum") or m.get("liquidity"))))
        time.sleep(0.3)
    if allwc:
        allwc.sort(reverse=True)
        tight = sum(1 for s, _, _ in allwc if s <= 0.01)
        print(f"  mercados WC con bid/ask: {len(allwc)} | con spread ≤1¢: {tight} "
              f"({tight/len(allwc)*100:.0f}%)")
        print("  los 5 de MAYOR spread (donde habría 'room'):")
        for s, q, liq in allwc[:5]:
            print(f"    {s*100:5.1f}¢ | liq ${(liq or 0):>9,.0f} | {(q or '')[:52]}")

    # Kalshi: serie de campeón del Mundial + orderbook
    print("\n[Kalshi] buscando serie de campeón del Mundial…")
    rs = gget(f"{KALSHI}/series?category=Sports")
    champ = None
    cands = []
    if rs.status_code == 200:
        series = rs.json().get("series", [])
        for s in series:
            tit = s.get("title", "").lower()
            tk = s.get("ticker", "")
            if ("world cup" in tit and "esports" not in tit and "esport" not in tit):
                cands.append((tk, s.get("title", "")))
                if "win" in tit or "champ" in tit or tk in ("KXWORLDCUP", "KXWCWINNER", "KXFIFAWINNER"):
                    champ = s
        print(f"  series FIFA WC (no-esports): {len(cands)} — ej: " +
              ", ".join(f"{t}" for t, _ in cands[:8]))
    if champ:
        print(f"  serie: {champ.get('ticker')} | {champ.get('title')}")
        rm = gget(f"{KALSHI}/markets?series_ticker={champ.get('ticker')}&status=open&limit=60")
        if rm.status_code == 200:
            mk = rm.json().get("markets", [])
            print(f"  mercados: {len(mk)}")
            for m in sorted(mk, key=lambda x: -(x.get("yes_bid") or 0))[:8]:
                yb, ya = m.get("yes_bid"), m.get("yes_ask")
                sp = (ya - yb) if (yb is not None and ya is not None) else None
                print(f"    {m.get('yes_sub_title') or m.get('ticker'):24} "
                      f"bid {yb}¢ ask {ya}¢ spread {sp}¢")
    else:
        print("  no se encontró serie de campeón clara (revisar 162 series WC manualmente)")


if __name__ == "__main__":
    main()
