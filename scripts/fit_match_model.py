#!/usr/bin/env python3
"""Calibra el motor de partido (Dixon-Coles sobre Elo) en intl_results → models/dc/.

Uso: python scripts/fit_match_model.py [--force] [--since 1990-01-01]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mova_data.db import get_db, init_db
from mova_model import match_model


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--since", default="1990-01-01")
    args = ap.parse_args()
    if match_model.exists() and not args.force:
        print("Params DC ya existen (--force para recalibrar):", match_model.load())
        return
    init_db()
    with get_db() as conn:
        params = match_model.fit(conn, since=args.since)
    match_model.save(params)
    print("Calibrado:", {k: round(v, 4) if isinstance(v, float) else v for k, v in params.items()})
    # sanity: partido parejo y partido desigual
    for dr in (0, 100, 300, -200):
        h, d, a = match_model.predict_1x2(dr, params)
        print(f"  dr={dr:+5d} → H={h:.3f} D={d:.3f} A={a:.3f}")


if __name__ == "__main__":
    main()
