#!/usr/bin/env python3
"""Scouting táctico de un cruce desde eventos WC2026.

Uso: python scripts/scout.py "Colombia" "Ghana"
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mova_data.db import get_db, init_db
from mova_model import scouting

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print('Uso: python scripts/scout.py "Equipo A" "Equipo B"'); sys.exit(1)
    init_db()
    with get_db() as conn:
        print(scouting.matchup(conn, sys.argv[1], sys.argv[2]))
