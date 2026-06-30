#!/usr/bin/env python3
"""Carga el mirror football-data.co.uk (clubes) → SQLite data/betting.db.

Fuente: github.com/huhao930422-debug/football-odds-mirror (mirror diario).
Tabla `club_matches`: resultado + odds de APERTURA (PSH/B365H) y CIERRE (PSCH/B365CH)
+ agregados de mercado. Idempotente (INSERT OR REPLACE por PK natural).
Uso: python scripts/collect_club_odds.py
"""
import csv
import datetime as dt
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "club-odds-mirror" / "data"
DB = ROOT / "data" / "betting.db"

# Columnas de odds a conservar (apertura = sin C, cierre = con C)
ODDS_COLS = [
    "PSH", "PSD", "PSA", "PSCH", "PSCD", "PSCA",          # Pinnacle open / close
    "B365H", "B365D", "B365A", "B365CH", "B365CD", "B365CA",  # Bet365 open / close
    "AvgH", "AvgD", "AvgA", "AvgCH", "AvgCD", "AvgCA",    # market avg open / close
    "MaxH", "MaxD", "MaxA", "MaxCH", "MaxCD", "MaxCA",    # market max open / close
]

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS club_matches (
    league TEXT, season TEXT, match_date TEXT,
    home_team TEXT, away_team TEXT,
    fthg INTEGER, ftag INTEGER, ftr TEXT,
    {', '.join(f'{c} REAL' for c in ODDS_COLS)},
    PRIMARY KEY (league, season, match_date, home_team, away_team)
);
CREATE INDEX IF NOT EXISTS idx_club_date ON club_matches(match_date);
CREATE INDEX IF NOT EXISTS idx_club_league ON club_matches(league, season);
"""


def parse_date(s):
    s = (s or "").strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return dt.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def i(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def main():
    if not SRC.exists():
        sys.exit(f"No existe {SRC} — corre: git clone --depth 1 "
                 "https://github.com/huhao930422-debug/football-odds-mirror.git "
                 "data/club-odds-mirror")
    conn = sqlite3.connect(DB)
    conn.executescript(SCHEMA)
    files = sorted(SRC.glob("*/season-*.csv"))
    total, kept, with_close = 0, 0, 0
    for fp in files:
        league = fp.parent.name
        season = fp.stem.replace("season-", "")
        try:
            rows = list(csv.DictReader(open(fp, encoding="utf-8-sig", errors="replace")))
        except Exception as e:                       # noqa: BLE001
            print(f"  skip {fp}: {e}")
            continue
        batch = []
        for r in rows:
            total += 1
            d = parse_date(r.get("Date"))
            home, away, ftr = r.get("HomeTeam"), r.get("AwayTeam"), r.get("FTR")
            if not (d and home and away and ftr in ("H", "D", "A")):
                continue
            vals = [league, season, d, home, away, i(r.get("FTHG")), i(r.get("FTAG")), ftr]
            vals += [f(r.get(c)) for c in ODDS_COLS]
            batch.append(vals)
            kept += 1
            if r.get("PSCH") and r.get("PSCA"):
                with_close += 1
        ph = ",".join("?" * (8 + len(ODDS_COLS)))
        conn.executemany(
            f"INSERT OR REPLACE INTO club_matches VALUES ({ph})", batch)
    conn.commit()
    n = conn.execute("SELECT COUNT(*) FROM club_matches").fetchone()[0]
    nclose = conn.execute(
        "SELECT COUNT(*) FROM club_matches WHERE PSCH IS NOT NULL AND PSCA IS NOT NULL"
    ).fetchone()[0]
    rng = conn.execute("SELECT MIN(match_date), MAX(match_date) FROM club_matches").fetchone()
    print(f"Archivos: {len(files)} | filas leídas: {total:,} | cargadas: {n:,}")
    print(f"Con cierre Pinnacle (PSCH&PSCA): {nclose:,}")
    print(f"Rango de fechas: {rng[0]} -> {rng[1]}")
    conn.close()


if __name__ == "__main__":
    main()
