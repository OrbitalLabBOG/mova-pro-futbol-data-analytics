#!/usr/bin/env python3
"""Entrena el modelo xG NATIVO de WhoScored (con BigChance) y lo persiste.

WhoScored trae is_goal + BigChance → xG calibrado a los datos que puntuamos y que
captura calidad de ocasión (mano a mano/contraataque), evitando el sesgo de proveedor.
Métricas honestas por k-fold. StatsBomb queda como referencia opcional (--source statsbomb).

Uso: python scripts/train_xg.py [--force] [--source whoscored|statsbomb]
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mova_data.config import RAW_DIR
from mova_data.db import get_db
from mova_model import shots, xg_model
from sklearn.metrics import brier_score_loss, roc_auc_score, log_loss
from sklearn.model_selection import cross_val_predict
from sklearn.linear_model import LogisticRegression


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--source", choices=["whoscored", "statsbomb"], default="whoscored")
    args = ap.parse_args()
    if xg_model.exists() and not args.force:
        print("Modelo xG ya existe (--force para reentrenar):", xg_model.load()[1].get("version"))
        return

    if args.source == "whoscored":
        with get_db() as conn:
            df = shots.from_whoscored(conn)
    else:
        df = shots.from_statsbomb(RAW_DIR / "statsbomb")
    print(f"Tiros {args.source}: {len(df)} | penales: {(df.play_type=='penalty').sum()} | goles: {df.is_goal.sum()}")

    fit = df[df.play_type != "penalty"]
    X = shots.design_matrix(fit)
    y = fit.is_goal.to_numpy(int)

    # ── Métricas honestas por k-fold (out-of-fold) ──
    oof = cross_val_predict(LogisticRegression(max_iter=2000), X, y, cv=5, method="predict_proba")[:, 1]
    print("\n[k-fold OOF] Brier=%.4f logloss=%.4f AUC=%.3f" % (
        brier_score_loss(y, oof), log_loss(y, oof, labels=[0, 1]), roc_auc_score(y, oof)))
    print(f"   suma xG OOF={oof.sum():.0f} vs goles reales(no-penal)={y.sum()} (insesgo agregado)")

    # ── Sanity: BigChance y geometría ──
    model, meta = xg_model.train(df)
    probe = pd.DataFrame([
        {"dist": 11, "angle": 0.5, "body_part": "foot", "play_type": "open", "is_big_chance": 0},
        {"dist": 11, "angle": 0.5, "body_part": "foot", "play_type": "open", "is_big_chance": 1},
        {"dist": 11, "angle": 0.5, "body_part": "head", "play_type": "open", "is_big_chance": 0},
        {"dist": 25, "angle": 0.2, "body_part": "foot", "play_type": "open", "is_big_chance": 0},
        {"dist": 11, "angle": 0.5, "body_part": "foot", "play_type": "penalty", "is_big_chance": 0},
    ])
    pr = xg_model.predict(model, probe)
    print(f"\n[Sanity] pie@11m={pr[0]:.3f} bigchance@11m={pr[1]:.3f} cabeza@11m={pr[2]:.3f} "
          f"lejano={pr[3]:.3f} penal={pr[4]:.3f}")
    assert pr[1] > pr[0] > pr[3], "BigChance debe subir y lejano bajar"

    meta["source"] = args.source
    v = xg_model.save(model, meta)
    print(f"\nGuardado models/xg/ version={v} (entrenado en {meta['n_train']} tiros {args.source})")


if __name__ == "__main__":
    main()
