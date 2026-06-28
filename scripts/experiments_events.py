"""¿Las features de evento/táctica (xG, set-pieces) mejoran la predicción?

Test honesto: WC2018+2022, features acumuladas dentro del torneo (leakage-free),
entrena WC2018 → evalúa WC2022. Compara feature sets anidados por RPS.
"""
import csv
import glob
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mova_data.config import RAW_DIR
from mova_data.db import get_db, init_db
from mova_data.teams import resolve
from mova_model import evaluate
from sklearn.linear_model import LogisticRegression

SETPIECE_PP = {"From Corner", "From Free Kick"}


def sb_match_feats(conn, comp_dir):
    """(date,ch,ca) → dict con xg y set-piece xg por lado."""
    base = RAW_DIR / "statsbomb" / comp_dir
    meta = {r["match_id"]: r for r in csv.DictReader(open(base / "_matches.csv"))}
    out = {}
    for f in glob.glob(str(base / "*.json")):
        m = meta.get(Path(f).stem)
        if not m:
            continue
        home = m["home_team"]
        agg = {}
        for e in json.load(open(f)):
            if e.get("type") == "Shot" and e.get("shot_statsbomb_xg") is not None:
                t = e.get("team"); xg = e["shot_statsbomb_xg"]
                d = agg.setdefault(t, [0.0, 0.0])     # [xg, setpiece_xg]
                d[0] += xg
                if e.get("play_pattern") in SETPIECE_PP:
                    d[1] += xg
        if home not in agg:
            continue
        away = next((k for k in agg if k != home), None)
        ch = resolve(conn, m["home_team"]) or m["home_team"]
        ca = resolve(conn, m["away_team"]) or m["away_team"]
        out[(m["match_date"], ch, ca)] = {
            "xgf_h": agg[home][0], "sp_h": agg[home][1],
            "xgf_a": agg.get(away, [0, 0])[0] if away else 0,
            "sp_a": agg.get(away, [0, 0])[1] if away else 0}
    return out


def build(conn, year, sbfeats):
    rows = conn.execute(
        """SELECT match_date,home_team,away_team,home_score,away_score,neutral,
                  home_elo_pre,away_elo_pre FROM intl_results
           WHERE tournament='FIFA World Cup' AND match_date LIKE ? ORDER BY match_date""",
        (year + "%",)).fetchall()
    hist = {}     # team → [xgf,xga,sp_for,sp_against,n]
    data = []
    for d, h, a, hs, as_, neu, eh, ea in rows:
        if hs is None or eh is None:
            continue
        ch, ca = resolve(conn, h) or h, resolve(conn, a) or a

        def avg(t):
            v = hist.get(t)
            return [v[i] / v[4] for i in range(4)] if v and v[4] else None
        fh, fa = avg(ch), avg(ca)
        dr = (eh - ea) + (0 if neu else 100)
        y = 0 if hs > as_ else (1 if hs == as_ else 2)
        # diferencias de matchup (None si falta historia)
        xg_d = (fh[0] - fh[1]) - (fa[0] - fa[1]) if fh and fa else 0.0
        sp_d = (fh[2] - fa[3]) - (fa[2] - fh[3]) if fh and fa else 0.0  # set-piece A vs def B
        has = fh is not None and fa is not None
        data.append(dict(dr=dr, xg_d=xg_d, sp_d=sp_d, y=y, has=has))
        # actualizar con xG real del partido
        sf = sbfeats.get((d, ch, ca))
        if sf:
            for t, xf, xa, spf, spa in ((ch, sf["xgf_h"], sf["xgf_a"], sf["sp_h"], sf["sp_a"]),
                                        (ca, sf["xgf_a"], sf["xgf_h"], sf["sp_a"], sf["sp_h"])):
                v = hist.setdefault(t, [0, 0, 0, 0, 0])
                v[0] += xf; v[1] += xa; v[2] += spf; v[3] += spa; v[4] += 1
    return data


def rps_for(tr, te, cols):
    X = lambda D: np.array([[r[c] for c in cols] for r in D], float)
    lr = LogisticRegression(max_iter=3000).fit(X(tr), [r["y"] for r in tr])
    return evaluate.rps(lr.predict_proba(X(te)), [r["y"] for r in te])


def main():
    init_db()
    with get_db() as conn:
        f18, f22 = sb_match_feats(conn, "wc-2018"), sb_match_feats(conn, "wc-2022")
        tr = build(conn, "2018", f18)
        te = build(conn, "2022", f22)
    # evaluar solo en partidos del test con historia de eventos (matchup real)
    te_xg = [r for r in te if r["has"]]
    tr_xg = [r for r in tr if r["has"]]
    print(f"Train WC2018={len(tr_xg)} con eventos | Test WC2022={len(te_xg)} con eventos\n")
    print("="*52); print("RPS en WC2022 (solo partidos con historia de evento)"); print("="*52)
    sets = {"elo": ["dr"], "elo+xG": ["dr", "xg_d"],
            "elo+xG+setpiece": ["dr", "xg_d", "sp_d"], "solo táctica": ["xg_d", "sp_d"]}
    base = rps_for(tr_xg, te_xg, ["dr"])
    for name, cols in sets.items():
        r = rps_for(tr_xg, te_xg, cols)
        tag = "" if name == "elo" else f"  ({(1-r/base)*100:+.1f}% vs elo)"
        print(f"  {name:20s} RPS={r:.4f}{tag}")


if __name__ == "__main__":
    main()
