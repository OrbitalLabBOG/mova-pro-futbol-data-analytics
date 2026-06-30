#!/usr/bin/env python3
"""Backtest de CLV: ¿le ganamos al cierre de Pinnacle? (clubes, leakage-free).

Modelo independiente del mercado: Elo de clubes WALK-FORWARD + calibración 1X2
(logit multinomial, ventana expansiva re-ajustada por año → sin fuga de información).
Luego confronta el modelo contra las líneas de APERTURA y CIERRE (Pinnacle de-vigado).

Tests:
  1. Skill predictivo: RPS modelo vs RPS cierre vs RPS apertura.
  2. Value betting + CLV: apostar apertura cuando el modelo ve valor; medir CLV, ROI, t-stat.
  3. Calibración del cierre (validación teórica: ¿el cierre ≈ verdad?).
  4. Batir el cierre directo: apostar al cierre cuando el modelo discrepa (test de edge puro).

Uso: python scripts/clv_backtest.py
"""
import math
import sqlite3
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "betting.db"

K_ELO = 20.0
HFA = 65.0            # ventaja local en puntos Elo
WARMUP_YEAR = 1996    # años previos solo construyen Elo; no se testean
IDX = {"H": 0, "D": 1, "A": 2}


def devig_mult(oh, od, oa):
    """Devig multiplicativo → (q_h, q_d, q_a) que suman 1."""
    inv = [1.0 / oh, 1.0 / od, 1.0 / oa]
    s = sum(inv)
    return [x / s for x in inv]


def rps(probs, outcome_idx):
    """Ranked Probability Score (3 salidas ordinales H<D<A). 0 = perfecto."""
    cp = np.cumsum(probs)
    co = np.cumsum([1.0 if i == outcome_idx else 0.0 for i in range(3)])
    return float(np.sum((cp - co) ** 2)) / 2.0


def load():
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        """SELECT match_date, home_team, away_team, ftr,
                  PSH, PSD, PSA, PSCH, PSCD, PSCA,
                  B365H, B365D, B365A
           FROM club_matches
           WHERE ftr IN ('H','D','A')
           ORDER BY match_date, home_team""").fetchall()
    conn.close()
    return rows


def main():
    rows = load()
    elo = {}
    feats, labels, year_of = [], [], []   # acumulador para entrenar el logit
    # estructuras de test
    test = []   # dicts por partido testeable

    def get(t):
        return elo.get(t, 1500.0)

    # Pase único cronológico: Elo walk-forward + recolección de features.
    # El logit se reentrena por año con TODO lo anterior (expansiva, sin fuga).
    clf = None
    last_train_year = None
    Xall, yall = [], []

    for r in rows:
        (date, home, away, ftr,
         psh, psd, psa, psch, pscd, psca,
         b3h, b3d, b3a) = r
        year = int(date[:4])
        rh, ra = get(home), get(away)
        dr = rh - ra + HFA
        oi = IDX[ftr]

        # --- ¿partido testeable? requiere apertura y cierre Pinnacle válidos ---
        open_odds = None
        if psh and psd and psa and psh > 1 and psd > 1 and psa > 1:
            open_odds = (psh, psd, psa)
        elif b3h and b3d and b3a and b3h > 1 and b3d > 1 and b3a > 1:
            open_odds = (b3h, b3d, b3a)
        close_ok = psch and pscd and psca and psch > 1 and pscd > 1 and psca > 1

        if year > WARMUP_YEAR and open_odds and close_ok and len(Xall) > 2000:
            # reentrenar logit si cambió el año
            if clf is None or year != last_train_year:
                clf = LogisticRegression(max_iter=1000)
                clf.fit(np.array(Xall).reshape(-1, 1), np.array(yall))
                last_train_year = year
            # predecir con coeficientes entrenados SOLO con el pasado
            p = clf.predict_proba(np.array([[dr]]))[0]
            cls = list(clf.classes_)
            model_p = [0.0, 0.0, 0.0]
            for j, c in enumerate(cls):
                model_p[c] = p[j]
            test.append({
                "model_p": model_p, "oi": oi,
                "open": open_odds,
                "q_close": devig_mult(psch, pscd, psca),
                "close": (psch, pscd, psca),
                "q_open": devig_mult(*open_odds),
            })

        # --- acumular para entrenamiento futuro (después de usar el pasado) ---
        if year > 1994:
            Xall.append(dr)
            yall.append(oi)

        # --- actualizar Elo (después de registrar todo) ---
        exp_h = 1.0 / (1.0 + 10 ** (-(rh - ra + HFA) / 400.0))
        score_h = 1.0 if ftr == "H" else (0.5 if ftr == "D" else 0.0)
        delta = K_ELO * (score_h - exp_h)
        elo[home] = rh + delta
        elo[away] = ra - delta

    n = len(test)
    print(f"Partidos testeables (apertura+cierre Pinnacle, leakage-free): {n:,}\n")
    if n < 1000:
        print("Muestra insuficiente."); return

    # ---------- TEST 1: skill predictivo (RPS) ----------
    rps_model = np.mean([rps(t["model_p"], t["oi"]) for t in test])
    rps_close = np.mean([rps(t["q_close"], t["oi"]) for t in test])
    rps_open = np.mean([rps(t["q_open"], t["oi"]) for t in test])
    sd = np.std([rps(t["q_close"], t["oi"]) for t in test])
    se = sd / math.sqrt(n)
    print("== TEST 1 · Skill predictivo (RPS, menor=mejor) ==")
    print(f"  Modelo (Elo+logit) : {rps_model:.4f}")
    print(f"  Cierre Pinnacle    : {rps_close:.4f}   <- benchmark sharp")
    print(f"  Apertura Pinnacle  : {rps_open:.4f}")
    print(f"  SE(RPS) ~ {se:.4f}  | Δ(modelo-cierre)={rps_model-rps_close:+.4f} "
          f"({(rps_model-rps_close)/se:+.1f} SE)")
    verdict = ("el modelo NO le gana al cierre" if rps_model > rps_close + 2 * se
               else "el modelo IGUALA/supera al cierre" if rps_model < rps_close - 2 * se
               else "empate estadístico con el cierre")
    print(f"  -> {verdict}\n")

    # ---------- TEST 2: value betting + CLV (apostar APERTURA) ----------
    print("== TEST 2 · Value betting vs apertura + CLV (clave) ==")
    print(f"  {'umbral EV':>9} | {'#apuestas':>9} | {'CLV medio':>9} | {'%CLV>0':>7} | "
          f"{'ROI':>7} | {'t-stat':>7}")
    for thr in (0.0, 0.02, 0.05, 0.10):
        clvs, rets = [], []
        for t in test:
            for o in range(3):
                ev = t["model_p"][o] * t["open"][o] - 1.0   # EV con prob del modelo
                if ev > thr:
                    odds_taken = t["open"][o]
                    q_close = t["q_close"][o]
                    clvs.append(odds_taken * q_close - 1.0)   # CLV = EV al cierre "justo"
                    rets.append((odds_taken - 1.0) if t["oi"] == o else -1.0)
        if len(rets) < 30:
            print(f"  {thr:9.0%} |  (pocas apuestas: {len(rets)})"); continue
        clvs, rets = np.array(clvs), np.array(rets)
        roi = rets.mean()
        tstat = roi / (rets.std() / math.sqrt(len(rets)))
        print(f"  {thr:9.0%} | {len(rets):9,} | {clvs.mean():+8.2%} | "
              f"{(clvs>0).mean():6.1%} | {roi:+6.2%} | {tstat:+6.2f}")
    print("  CLV>0 medio y consistente = edge real; ROI≈-vig y CLV≈0 = sin edge.\n")

    # ---------- TEST 3: calibración del cierre (validación teórica) ----------
    print("== TEST 3 · Calibración del cierre Pinnacle (¿cierre ≈ verdad?) ==")
    bins = np.linspace(0, 1, 11)
    ps, real = [], []
    for t in test:
        for o in range(3):
            ps.append(t["q_close"][o]); real.append(1.0 if t["oi"] == o else 0.0)
    ps, real = np.array(ps), np.array(real)
    print(f"  {'prob cierre':>12} | {'frec real':>10} | n")
    mce = 0.0
    for lo, hi in zip(bins[:-1], bins[1:]):
        m = (ps >= lo) & (ps < hi)
        if m.sum() > 50:
            pm, rm = ps[m].mean(), real[m].mean()
            mce += abs(pm - rm) * m.sum()
            print(f"  {lo:.1f}-{hi:.1f}  ~{pm:5.1%} | {rm:9.1%} | {m.sum():,}")
    print(f"  Error de calibración medio (ponderado): {mce/len(ps):.4f} "
          f"(≈0 = cierre casi perfecto)\n")

    # ---------- TEST 4: batir el cierre directo (edge puro) ----------
    print("== TEST 4 · Apostar al CIERRE cuando el modelo discrepa (edge puro) ==")
    for thr in (0.0, 0.05):
        rets = []
        for t in test:
            for o in range(3):
                if t["model_p"][o] * t["close"][o] - 1.0 > thr:
                    rets.append((t["close"][o] - 1.0) if t["oi"] == o else -1.0)
        if len(rets) >= 30:
            rets = np.array(rets)
            roi = rets.mean()
            tstat = roi / (rets.std() / math.sqrt(len(rets)))
            print(f"  umbral {thr:.0%}: #{len(rets):,} | ROI {roi:+.2%} | t={tstat:+.2f}")
    print("  (ROI≈-vig esperado: batir el cierre con un modelo simple es casi imposible.)")


if __name__ == "__main__":
    main()
