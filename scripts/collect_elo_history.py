#!/usr/bin/env python3
"""Baja histórico internacional (martj42) y calcula Elo propio → intl_results + elo_computed.

Histórico estático: correr una vez (o cuando se quiera refrescar resultados nuevos).
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mova_data.db import get_db, init_db
from mova_data.collectors import elo_history

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                    datefmt="%H:%M:%S")

if __name__ == "__main__":
    init_db()
    with get_db() as conn:
        print(elo_history.collect(conn))
