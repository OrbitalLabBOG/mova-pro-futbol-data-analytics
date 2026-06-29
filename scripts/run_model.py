#!/usr/bin/env python3
"""Orquestador de la capa de modelo (re-ejecutable con datos frescos del collector).

Uso:
    python scripts/run_model.py                 # corrida completa (estado actual de la DB)
    python scripts/run_model.py --retrain       # reentrena xG + recalibra motor
    python scripts/run_model.py --as-of 2026-06-28   # barrera de información (backtest/point-in-time)
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mova_model import pipeline
from mova_model.config import N_SIM, SEED

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                    datefmt="%H:%M:%S")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", default=None)
    ap.add_argument("--retrain", action="store_true")
    ap.add_argument("--n", type=int, default=N_SIM)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--w-market", type=float, default=0.65, help="peso del mercado en el anclaje del torneo")
    ap.add_argument("--no-live", action="store_true", help="no condicionar a partidos en vivo")
    args = ap.parse_args()
    res = pipeline.run(as_of=args.as_of, n_sims=args.n, seed=args.seed,
                       retrain=args.retrain, run_id=args.run_id, w_market=args.w_market,
                       no_live=args.no_live)
    print("OK:", res)
