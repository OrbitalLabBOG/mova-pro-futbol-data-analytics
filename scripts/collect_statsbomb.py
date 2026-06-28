#!/usr/bin/env python3
"""Cachea StatsBomb Open Data (WC2022/2018) para entrenar el modelo de xG.

Uso:
    python scripts/collect_statsbomb.py            # WC2022 + WC2018 completos
    python scripts/collect_statsbomb.py --max 5    # 5 partidos por torneo (prueba)
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mova_data.config import RAW_DIR
from mova_data.collectors import statsbomb

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                    datefmt="%H:%M:%S")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=None, help="máx partidos por torneo")
    args = ap.parse_args()
    statsbomb.collect(RAW_DIR / "statsbomb", max_matches=args.max)
