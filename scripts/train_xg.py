#!/usr/bin/env python3
"""Entrena el modelo xG propio sobre StatsBomb y lo persiste en models/xg/.

Validación de transferencia: entrena en WC2018, valida en WC2022 (Brier/log-loss/
calibración vs el xG oficial de StatsBomb). Luego reentrena en TODO y guarda.

Uso: python scripts/train_xg.py [--force]
"""
import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mova_data.config import RAW_DIR
from mova_model import shots, xg_model
from mova_model.evaluate import brier, logloss
from sklearn.metrics import brier_score_loss, roc_auc_score, log_loss


def _bin_metrics(y, p):
    return dict(brier=round(brier_score_loss(y, p), 4),
               logloss=round(log_loss(y, p, labels=[0, 1]), 4),
               auc=round(roc_auc_score(y, p), 3))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    if xg_model.exists() and not args.force:
        print("Modelo xG ya existe (usa --force para reentrenar).", xg_model.load()[1].get("version"))
        return

    df = shots.from_statsbomb(RAW_DIR / "statsbomb")
    print(f"Tiros StatsBomb: {len(df)} | con penales: {(df.play_type=='penalty').sum()} | goles: {df.is_goal.sum()}")

    # ── Validación de transferencia WC2018 → WC2022 ──
    tr = df[df.competition == "wc-2018"]
    te = df[df.competition == "wc-2022"]
    if len(tr) and len(te):
        m, _ = xg_model.train(tr)
        te_np = te[te.play_type != "penalty"]
        p = xg_model.predict(m, te_np)
        y = te_np.is_goal.to_numpy()
        print("\n[Transferencia] train=WC2018 test=WC2022 (sin penales):")
        print("   nuestro xG:", _bin_metrics(y, p))
        print("   xG StatsBomb (ref):", _bin_metrics(y, te_np.xg_sb.to_numpy()))
        print(f"   suma xG nuestro={p.sum():.1f} vs goles reales={y.sum()} (insesgo agregado)")

    # ── Sanity: cabezazo < pie a igual distancia ──
    import pandas as pd
    probe = pd.DataFrame([
        {"dist": 11, "angle": 0.5, "body_part": "foot", "play_type": "open"},
        {"dist": 11, "angle": 0.5, "body_part": "head", "play_type": "open"},
        {"dist": 25, "angle": 0.2, "body_part": "foot", "play_type": "open"},
        {"dist": 11, "angle": 0.5, "body_part": "foot", "play_type": "penalty"},
    ])
    mfull, meta = xg_model.train(df)
    pr = xg_model.predict(mfull, probe)
    print(f"\n[Sanity] pie@11m={pr[0]:.3f} cabeza@11m={pr[1]:.3f} pie@25m={pr[2]:.3f} penal={pr[3]:.3f}")
    assert pr[0] > pr[1] and pr[0] > pr[2], "sanity falló (pie cercano debe ser mayor)"

    v = xg_model.save(mfull, meta)
    print(f"\nGuardado models/xg/ version={v} (entrenado en {meta['n_train']} tiros)")


if __name__ == "__main__":
    main()
