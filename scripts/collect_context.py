#!/usr/bin/env python3
"""Collector de fuentes de contexto: Elo + Kalshi + ESPN.

Ligero, sin browser, ideal para correr a diario (cron) y construir series
temporales de ratings y probabilidades de mercado.

Uso:
    python scripts/collect_context.py            # las tres
    python scripts/collect_context.py --only elo,kalshi
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mova_data.db import get_db, init_db
from mova_data.collectors import elo, kalshi, espn

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("mova.context")

SOURCES = {"elo": elo.collect, "kalshi": kalshi.collect, "espn": espn.collect}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="csv: elo,kalshi,espn")
    args = ap.parse_args()
    which = args.only.split(",") if args.only else list(SOURCES)

    init_db()
    with get_db() as conn:
        for name in which:
            fn = SOURCES.get(name.strip())
            if not fn:
                log.warning("fuente desconocida: %s", name); continue
            try:
                fn(conn)
            except Exception as e:
                log.error("%s falló: %s", name, e)
    log.info("Contexto actualizado.")


if __name__ == "__main__":
    main()
