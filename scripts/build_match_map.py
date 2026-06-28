#!/usr/bin/env python3
"""Construye match_map (enlace de partidos entre fuentes). Re-ejecutable."""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mova_data.db import get_db, init_db
from mova_data.matches_map import build_match_map

logging.basicConfig(level=logging.INFO, format="%(message)s")

if __name__ == "__main__":
    init_db()
    with get_db() as conn:
        info = build_match_map(conn)
    print("match_map:", info)
