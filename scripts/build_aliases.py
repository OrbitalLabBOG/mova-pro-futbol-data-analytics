#!/usr/bin/env python3
"""Puebla team_aliases y audita la cobertura de nombres en cada fuente.

Reporta nombres que NO resuelven a un equipo canónico — deben ser solo
placeholders de fixtures futuros (ESPN 'Round of 32 X Winner') o equipos no
clasificados en mercados (Polymarket Italy/Peru/Team AG...).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mova_data.db import get_db, init_db
from mova_data import teams

SOURCES = {
    "Kalshi":     "SELECT DISTINCT entity FROM market_odds WHERE source='kalshi'",
    "Polymarket": "SELECT DISTINCT entity FROM market_odds WHERE source='polymarket'",
    "OddsAPI":    "SELECT DISTINCT entity FROM market_odds WHERE source='oddsapi'",
    "ESPN":       "SELECT home_team FROM espn_fixtures UNION SELECT away_team FROM espn_fixtures",
    "Elo":        "SELECT DISTINCT team FROM elo_ratings WHERE team IS NOT NULL",
    "WhoScored":  "SELECT home_team FROM matches UNION SELECT away_team FROM matches",
}


def main():
    init_db()
    with get_db() as conn:
        info = teams.build_aliases(conn)
        print(f"team_aliases poblada: {info['canonical']} canónicos, {info['aliases']} aliases\n")
        for label, sql in SOURCES.items():
            names = sorted(set(r[0] for r in conn.execute(sql) if r[0]))
            unresolved = [n for n in names if teams.resolve(conn, n) is None]
            ok = len(names) - len(unresolved)
            print(f"{label}: {ok}/{len(names)} resueltos")
            if unresolved:
                print(f"    sin resolver ({len(unresolved)}): {unresolved}")


if __name__ == "__main__":
    main()
