#!/usr/bin/env python3
"""Explora fuentes de contexto ANTES de diseñar tablas.

Descarga muestras reales, las cachea crudas en data/raw/_explore/, y vuelca
la estructura (campos + tipos + rangos) de cada fuente:
  - Elo (eloratings.net)
  - Kalshi (mercados Mundial)
  - ESPN (fixtures + odds)
  - StatsBomb Open Data (event data histórico para entrenar)
"""
import json
import sys
import urllib.request
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mova_data.config import RAW_DIR

EXP = RAW_DIR / "_explore"
EXP.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0"}


def get_json(url, headers=None):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    return json.load(urllib.request.urlopen(req, timeout=30))


def get_text(url):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")


def hr(t):
    print("\n" + "=" * 72 + f"\n{t}\n" + "=" * 72)


# ── 1) ELO ──────────────────────────────────────────────────────────
def explore_elo():
    hr("1) ELO — eloratings.net/World.tsv")
    txt = get_text("https://www.eloratings.net/World.tsv")
    (EXP / "elo_World.tsv").write_text(txt)
    lines = txt.strip().splitlines()
    print(f"filas: {len(lines)} | columnas (1ra fila): {len(lines[0].split(chr(9)))}")
    print("primeras 3 filas crudas (tab-separated):")
    for ln in lines[:3]:
        print("  ", ln.split("\t"))
    print("→ interpretación: col0=rank, col2=ISO, col3=rating (resto deltas/contadores)")


# ── 2) KALSHI ───────────────────────────────────────────────────────
def explore_kalshi():
    hr("2) KALSHI — KXMENWORLDCUP (ganador del Mundial)")
    j = get_json("https://api.elections.kalshi.com/trade-api/v2/markets"
                 "?series_ticker=KXMENWORLDCUP&status=open&limit=60")
    (EXP / "kalshi_winner.json").write_text(json.dumps(j))
    ms = j.get("markets", [])
    print(f"markets: {len(ms)}")
    if ms:
        print("campos de un market:", list(ms[0].keys()))
        priced = [m for m in ms if m.get("last_price") or m.get("yes_ask")]
        print(f"con precio: {len(priced)}/{len(ms)}")
        for m in sorted(priced, key=lambda x: -(x.get("last_price") or 0))[:8]:
            print(f"  {m.get('ticker'):26s} last={m.get('last_price')} "
                  f"bid={m.get('yes_bid')} ask={m.get('yes_ask')} "
                  f"$={m.get('last_price_dollars')} | {m.get('yes_sub_title')}")
    # otras series WC
    hr("2b) KALSHI — series del Mundial disponibles")
    try:
        sj = get_json("https://api.elections.kalshi.com/trade-api/v2/series/"
                      "?category=Sports&limit=200")
        wc = [s for s in sj.get("series", []) if "WORLDCUP" in s.get("ticker", "").upper()
              or "WORLD CUP" in (s.get("title", "") or "").upper()]
        for s in wc[:20]:
            print(f"  {s.get('ticker'):22s} {s.get('title')}")
    except Exception as e:
        print("series list:", e)


# ── 3) ESPN ─────────────────────────────────────────────────────────
def explore_espn():
    hr("3) ESPN — scoreboard fifa.world (fixtures + odds)")
    j = get_json("https://site.api.espn.com/apis/site/v2/sports/soccer/"
                 "fifa.world/scoreboard?dates=20260628-20260703&limit=100")
    (EXP / "espn_scoreboard.json").write_text(json.dumps(j))
    evs = j.get("events", [])
    print(f"events: {len(evs)}")
    if evs:
        e = evs[0]; comp = e["competitions"][0]
        print("campos event:", list(e.keys()))
        print("campos competition:", list(comp.keys()))
        print("campos competitor:", list(comp["competitors"][0].keys()))
        odds = comp.get("odds")
        if odds:
            o = odds[0]
            print("odds provider:", o.get("provider", {}).get("name"))
            print("odds campos:", list(o.keys()))
            print("  moneyline:", {k: v.get("current", v) if isinstance(v, dict) else v
                                   for k, v in (o.get("moneyline") or {}).items()})
    hr("3b) ESPN — FIFA world ranking (si existe endpoint)")
    try:
        rj = get_json("https://site.api.espn.com/apis/site/v2/sports/soccer/"
                      "fifa.world/standings")
        print("standings top keys:", list(rj.keys())[:10])
    except Exception as ex:
        print("standings:", ex)


# ── 4) STATSBOMB ────────────────────────────────────────────────────
def explore_statsbomb():
    hr("4) STATSBOMB Open Data — competiciones disponibles")
    try:
        from statsbombpy import sb
    except ImportError:
        print("statsbombpy no instalado"); return
    comps = sb.competitions()
    (EXP / "statsbomb_competitions.csv").write_text(comps.to_csv(index=False))
    print("columnas:", list(comps.columns))
    wc = comps[comps["competition_name"].str.contains("World Cup", case=False, na=False)]
    print("\nMundiales / torneos de selección disponibles:")
    for _, r in wc.iterrows():
        print(f"  comp_id={r['competition_id']} season_id={r['season_id']} "
              f"{r['competition_name']} {r['season_name']}")
    # muestra de eventos de un partido WC2022 si existe
    try:
        wc22 = comps[(comps.competition_name.str.contains("World Cup", case=False, na=False))
                     & (comps.season_name == "2022")]
        if len(wc22):
            cid = int(wc22.iloc[0].competition_id); sid = int(wc22.iloc[0].season_id)
            matches = sb.matches(competition_id=cid, season_id=sid)
            print(f"\nWC2022: {len(matches)} partidos. Columnas matches:", list(matches.columns)[:12])
            mid = int(matches.iloc[0].match_id)
            ev = sb.events(match_id=mid)
            (EXP / f"statsbomb_events_{mid}.csv").write_text(ev.head(50).to_csv(index=False))
            print(f"events de un partido: {len(ev)} filas, {len(ev.columns)} columnas")
            print("columnas events (muestra):", list(ev.columns)[:25])
            print("tipos de evento:", ev["type"].value_counts().head(8).to_dict())
    except Exception as ex:
        print("muestra eventos:", ex)


if __name__ == "__main__":
    for fn in (explore_elo, explore_kalshi, explore_espn, explore_statsbomb):
        try:
            fn()
        except Exception as e:
            print(f"\n[ERROR en {fn.__name__}]: {e}")
    print(f"\nMuestras crudas guardadas en: {EXP}")
