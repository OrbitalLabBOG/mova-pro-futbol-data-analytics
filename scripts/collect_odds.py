#!/usr/bin/env python3
"""The Odds API (credit-metered, ~4 créditos/corrida en 1 región).

Uso:
    python scripts/collect_odds.py                    # winner + match (eu)
    python scripts/collect_odds.py --regions eu,uk    # más casas (más créditos)
    python scripts/collect_odds.py --winner-only      # solo ganador (1 crédito)
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mova_data.db import get_db, init_db
from mova_data.collectors import oddsapi

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                    datefmt="%H:%M:%S")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--regions", default="eu")
    ap.add_argument("--winner-only", action="store_true")
    ap.add_argument("--match-only", action="store_true")
    args = ap.parse_args()
    init_db()
    with get_db() as conn:
        r = oddsapi.collect(conn, regions=args.regions,
                            winner=not args.match_only,
                            match=not args.winner_only)
    print("Resultado:", r)
