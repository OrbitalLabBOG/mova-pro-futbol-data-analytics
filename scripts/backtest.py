#!/usr/bin/env python3
"""Backtest del modelo sobre WC2018+2022. Compara variantes por RPS (leakage-free).

Uso: python scripts/backtest.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mova_data.db import get_db, init_db
from mova_model import backtest


def main():
    init_db()
    with get_db() as conn:
        res = backtest.run(conn)
    print("="*64)
    print("BACKTEST WC2018+2022 (128 partidos, leakage-free)")
    print("="*64)
    print(f"{'θ (peso xG)':>12s} {'RPS':>8s} {'Brier':>8s} {'logloss':>8s} {'RPS(subset xG)':>15s}")
    base = res[0.0]["rps"]
    for theta, m in res.items():
        skill = (1 - m["rps"]/base) * 100
        rx = f"{m['rps_xg']:.4f}" if m['rps_xg'] is not None else "—"
        tag = "  ← Elo puro (baseline)" if theta == 0 else f"  (skill vs Elo: {skill:+.1f}%)"
        print(f"{theta:>12.1f} {m['rps']:8.4f} {m['brier']:8.4f} {m['logloss']:8.4f} {rx:>15s}{tag}")
    print(f"\nn={res[0.0]['n']} partidos | subset con historia xG: {res[0.0]['n_xg']}")
    print("\nReferencia (docs/08): bookies RPS≈0.20, ensembles fuertes≈0.19, SDR-Elo≈0.127")


if __name__ == "__main__":
    main()
