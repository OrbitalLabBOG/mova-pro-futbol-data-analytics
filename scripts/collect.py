#!/usr/bin/env python3
"""Collector MOVA Mundial 2026 — WhoScored.

Pipeline: discover (fixtures) → fetch (match centre, cacheado) → load (SQLite).

Uso:
    python scripts/collect.py                 # todo: discover + fetch finalizados + load
    python scripts/collect.py --discover-only # solo lista fixtures
    python scripts/collect.py --limit 5       # fetch máximo 5 partidos (prueba)
    python scripts/collect.py --include-unfinished  # también partidos en curso/programados
    python scripts/collect.py --load-only     # solo recargar cache → DB

Re-ejecutable: no re-descarga partidos ya cacheados (usar --force para forzar).
"""
import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mova_data.config import RAW_DIR, DB_PATH
from mova_data.collectors.whoscored import WhoScoredCollector
from mova_data.loaders import whoscored as loader
from mova_data.db import get_db, init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("mova.collect")

WS_RAW = RAW_DIR / "whoscored"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--discover-only", action="store_true")
    ap.add_argument("--load-only", action="store_true")
    ap.add_argument("--include-unfinished", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    init_db()

    if args.load_only:
        loader.load_dir(WS_RAW)
        return

    collector = WhoScoredCollector(WS_RAW)

    # 1) Discover
    fixtures = collector.discover()
    with get_db() as conn:
        loader.upsert_fixtures(fixtures, conn)
    log.info("Fixtures en DB: %d", len(fixtures))

    if args.discover_only:
        for f in fixtures:
            flag = "✓" if f["is_finished"] else "·"
            log.info("  %s [%s] %s %s-%s %s", flag, f["stage_name"],
                     f["home_team"], f["home_score"], f["away_score"], f["away_team"])
        return

    # 2) Fetch
    targets = [f for f in fixtures if args.include_unfinished or f["is_finished"]]
    if args.limit:
        targets = targets[: args.limit]
    log.info("A descargar: %d partidos", len(targets))

    ok = fail = cached = 0
    for i, f in enumerate(targets, 1):
        mid = f["match_id"]
        if collector.is_cached(mid) and not args.force:
            cached += 1
            continue
        log.info("[%d/%d] %s vs %s (%s)", i, len(targets),
                 f["home_team"], f["away_team"], f["stage_name"])
        if collector.fetch(mid, force=args.force):
            ok += 1
        else:
            fail += 1
        time.sleep(collector.delay)
    log.info("Fetch: %d nuevos, %d ya cacheados, %d fallos", ok, cached, fail)

    # 3) Load
    loader.load_dir(WS_RAW)
    log.info("DB lista: %s", DB_PATH)


if __name__ == "__main__":
    main()
