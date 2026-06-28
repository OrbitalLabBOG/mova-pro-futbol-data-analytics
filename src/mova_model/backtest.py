"""Backtest leakage-free sobre WC2018 + WC2022 (StatsBomb + Elo propio pre-partido).

Walk-forward DENTRO de cada torneo: cada partido se predice con Elo pre-partido
(ya leakage-free) + xG acumulado SOLO de partidos anteriores del mismo equipo en
ese torneo (igual que usamos WC2026: predecir R32 con el xG de los 3 de grupo).
Compara variantes por RPS/Brier/logloss.
"""
from __future__ import annotations

import csv
import glob
import json
from pathlib import Path

import numpy as np

from mova_data.config import RAW_DIR
from mova_data.teams import resolve
from . import match_model, elo, evaluate

SB_DIRS = {"2018": "wc-2018", "2022": "wc-2022"}


def _sb_match_xg(conn, comp_dir: str) -> dict:
    """(date, canon_home, canon_away) → (xg_home, xg_away) desde shots StatsBomb."""
    base = RAW_DIR / "statsbomb" / comp_dir
    meta = {r["match_id"]: r for r in csv.DictReader(open(base / "_matches.csv"))}
    out = {}
    for f in glob.glob(str(base / "*.json")):
        mid = Path(f).stem
        m = meta.get(mid)
        if not m:
            continue
        evs = json.load(open(f))
        home_name = m["home_team"]
        xg = {}
        for e in evs:
            if e.get("type") == "Shot" and e.get("shot_statsbomb_xg") is not None:
                xg[e.get("team")] = xg.get(e.get("team"), 0.0) + e["shot_statsbomb_xg"]
        teams_in = list(xg.keys())
        if len(teams_in) < 1:
            continue
        ch = resolve(conn, m["home_team"]) or m["home_team"]
        ca = resolve(conn, m["away_team"]) or m["away_team"]
        xh = xg.get(home_name, 0.0)
        xa = sum(v for k, v in xg.items() if k != home_name)
        out[(m["match_date"], ch, ca)] = (xh, xa)
    return out


def _accumulate(matches, sbxg):
    """Para cada partido, agrega xGF/xGA medios previos (en el torneo) por equipo."""
    hist = {}                       # team → [sum_xgf, sum_xga, n]
    feats = []
    for d, h, a, hs, as_, eh, ea in matches:
        def avg(t):
            v = hist.get(t)
            if not v or v[2] == 0:
                return None, None
            return v[0] / v[2], v[1] / v[2]
        xgf_h, xga_h = avg(h)
        xgf_a, xga_a = avg(a)
        feats.append((d, h, a, hs, as_, eh, ea, xgf_h, xga_h, xgf_a, xga_a))
        # actualizar con el resultado real de xG de este partido
        xg = sbxg.get((d, h, a))
        if xg:
            for t, f, ag in ((h, xg[0], xg[1]), (a, xg[1], xg[0])):
                v = hist.setdefault(t, [0.0, 0.0, 0])
                v[0] += f; v[1] += ag; v[2] += 1
    return feats


def load_matches(conn, year: str):
    rows = conn.execute(
        """SELECT match_date, home_team, away_team, home_score, away_score,
                  home_elo_pre, away_elo_pre
           FROM intl_results WHERE tournament='FIFA World Cup' AND match_date LIKE ?
           ORDER BY match_date""", (year + "%",)).fetchall()
    # resolver a canónico
    out = []
    for d, h, a, hs, as_, eh, ea in rows:
        out.append((d, resolve(conn, h) or h, resolve(conn, a) or a, hs, as_, eh, ea))
    return out


def _outcome(hs, as_):
    return 0 if hs > as_ else (1 if hs == as_ else 2)


def run(conn, thetas=(0.0, 0.2, 0.4, 0.6, 0.8), params=None) -> dict:
    params = params or match_model.load()
    feats_all = []
    for year, d in SB_DIRS.items():
        sbxg = _sb_match_xg(conn, d)
        feats_all += _accumulate(load_matches(conn, year), sbxg)

    results = {}
    for theta in thetas:
        P, Y, Pk, Yk = [], [], [], []
        for d, h, a, hs, as_, eh, ea, xgf_h, xga_h, xgf_a, xga_a in feats_all:
            if hs is None or eh is None:
                continue
            dr = elo.dr(eh, ea, neutral=True)
            lh, la = match_model.lambdas_xg(dr, xgf_h, xga_h, xgf_a, xga_a, params, theta)
            probs = match_model.p_1x2(match_model.score_matrix(lh, la, params["rho"]))
            y = _outcome(hs, as_)
            P.append(probs); Y.append(y)
            if xgf_h is not None and xgf_a is not None:   # subset con historia xG
                Pk.append(probs); Yk.append(y)
        results[theta] = {
            "n": len(P), "rps": evaluate.rps(P, Y), "brier": evaluate.brier(P, Y),
            "logloss": evaluate.logloss(P, Y),
            "n_xg": len(Pk), "rps_xg": evaluate.rps(Pk, Yk) if Pk else None,
        }
    return results
