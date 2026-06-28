#!/usr/bin/env python3
"""Banco de experimentos: ¿aprender pesos con ML ayuda? ¿la forma? ¿el xG? (leakage-free).

Entrena en partidos ANTES de cada Mundial y evalúa en WC2018/2022 (held-out).
Compara RPS contra el baseline Elo-Poisson.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mova_data.db import get_db, init_db
from mova_model import match_model, elo, evaluate, backtest as bt
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier

BARRIERS = {"2018": "2018-06-01", "2022": "2022-11-01"}


def load_all(conn):
    """Todos los partidos internacionales con Elo pre + forma reciente (goles)."""
    rows = conn.execute(
        """SELECT match_date, home_team, away_team, home_score, away_score,
                  neutral, home_elo_pre, away_elo_pre
           FROM intl_results WHERE home_elo_pre IS NOT NULL ORDER BY match_date""").fetchall()
    form = {}            # team → list de goal-diff recientes
    data = []
    for d, h, a, hs, as_, neu, eh, ea in rows:
        if hs is None or eh is None:
            continue
        fh = np.mean(form.get(h, [0])[-10:]) if form.get(h) else 0.0
        fa = np.mean(form.get(a, [0])[-10:]) if form.get(a) else 0.0
        dr = (eh - ea) + (0 if neu else 100)
        y = 0 if hs > as_ else (1 if hs == as_ else 2)
        data.append(dict(date=d, dr=dr, eh=eh, ea=ea, fh=fh, fa=fa,
                         neutral=neu, y=y))
        form.setdefault(h, []).append(hs - as_)
        form.setdefault(a, []).append(as_ - hs)
    return data


def elo_poisson_probs(rows, params):
    P = []
    for r in rows:
        lh, la = match_model.lambdas(r["dr"], params)
        P.append(match_model.p_1x2(match_model.score_matrix(lh, la, params["rho"])))
    return np.array(P)


def feat(rows, cols):
    return np.array([[r[c] for c in cols] for r in rows], dtype=float)


def evalsplit(data, params, feature_sets):
    """Para cada Mundial: entrena<barrera, evalúa en el torneo. Devuelve RPS por modelo."""
    out = {}
    for yr, bar in BARRIERS.items():
        tr = [r for r in data if r["date"] < bar]
        te = [r for r in data if r["date"][:4] == yr and r["date"] >= bar
              and r["date"][5:7] in (("06", "07") if yr == "2018" else ("11", "12"))]
        # restringir test a partidos de Mundial (los 64): usar intl tournament filter
        ytr = np.array([r["y"] for r in tr])
        yte = np.array([r["y"] for r in te])
        res = {}
        # baseline Elo-Poisson
        res["Elo-Poisson"] = evaluate.rps(elo_poisson_probs(te, params), yte)
        # modelos ML por feature set
        for name, cols in feature_sets.items():
            Xtr, Xte = feat(tr, cols), feat(te, cols)
            lr = LogisticRegression(max_iter=3000, C=1.0).fit(Xtr, ytr)
            res[f"LR[{name}]"] = evaluate.rps(lr.predict_proba(Xte), yte)
            if len(cols) >= 2:
                gb = HistGradientBoostingClassifier(max_depth=3, max_iter=200,
                                                    learning_rate=0.05).fit(Xtr, ytr)
                res[f"GBM[{name}]"] = evaluate.rps(gb.predict_proba(Xte), yte)
        out[yr] = (res, len(te))
    return out


def main():
    init_db()
    with get_db() as conn:
        params = match_model.load()
        data = load_all(conn)
        print(f"Dataset: {len(data)} partidos internacionales con Elo+forma")
        fs = {"elo": ["dr"], "elo+form": ["dr", "fh", "fa"],
              "elo+form+abs": ["dr", "fh", "fa", "eh", "ea"]}
        out = evalsplit(data, params, fs)

    print("\n" + "="*60); print("RPS por modelo (held-out, menor=mejor)"); print("="*60)
    models = list(next(iter(out.values()))[0].keys())
    print(f"{'modelo':22s} " + "  ".join(f"WC{y}" for y in out))
    for m in models:
        line = f"{m:22s} " + "  ".join(f"{out[y][0][m]:.4f}" for y in out)
        base = all(out[y][0][m] <= out[y][0]['Elo-Poisson'] for y in out)
        print(line + ("  ✓ ≤ baseline ambos" if base and m != 'Elo-Poisson' else ""))
    print(f"\nTest: WC2018={out['2018'][1]} part., WC2022={out['2022'][1]} part.")


if __name__ == "__main__":
    main()
