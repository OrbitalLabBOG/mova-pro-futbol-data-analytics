"""Aplica el xG a los tiros WhoScored y deriva fuerzas/forma por equipo.

- apply_xg: puntúa tiros WS con el modelo → tabla shot_xg.
- compute_team_features: xGF/xGA por partido (vía match_id), att/def normalizadas,
  Elo propio + ajuste de FORMA basado en xG del torneo (acotado; Elo sigue dominando).
"""
from __future__ import annotations

import datetime as dt

import numpy as np

from . import shots, elo, xg_model

# Ajuste de forma xG en el CORE: DESACTIVADO por evidencia de backtest.
# El backtest WC2018/22 mostró que meter xG al ranking no mejora el RPS
# (mejor caso +0.2%, ruido; más peso empeora). El Elo puro es el mejor core.
# El xG se conserva para la CAPA DE INSIGHT (regresión/suerte), no para el ranking.
XG_FORM_K = 0.0
XG_FORM_CAP = 100.0


def apply_xg(conn, model, version: str) -> int:
    """Puntúa tiros WhoScored y escribe shot_xg (idempotente)."""
    df = shots.from_whoscored(conn)
    if df.empty:
        return 0
    df = df.assign(xg=xg_model.predict(model, df))
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    conn.executemany(
        """INSERT OR REPLACE INTO shot_xg
           (source, match_id, shot_uid, team, player_id, minute, dist_m, angle_rad,
            body_part, play_type, is_big_chance, xg_model, xg_statsbomb, is_goal,
            model_version, generated_at)
           VALUES ('whoscored',?,?,?,?,?,?,?,?,?,?,?,NULL,?,?,?)""",
        [(r.match_id, r.shot_uid, r.team, int(r.player_id) if r.player_id is not None else None,
          int(r.minute) if r.minute is not None else None, float(r.dist), float(r.angle),
          r.body_part, r.play_type, int(r.is_big_chance), float(r.xg), int(r.is_goal),
          version, now) for r in df.itertuples()],
    )
    conn.commit()
    return len(df)


def compute_team_features(conn, run_id: str, as_of_date: str | None = None) -> dict:
    """Calcula y escribe team_features para los equipos del torneo."""
    # xG por (match_id, team) desde shot_xg, opcional barrera temporal
    q = """SELECT s.match_id, s.team, SUM(s.xg_model) xg
           FROM shot_xg s WHERE s.source='whoscored'"""
    args = []
    if as_of_date:
        q += """ AND s.match_id IN (SELECT match_id FROM matches
                 WHERE start_utc IS NULL OR substr(start_utc,1,10) <= ?)"""
        args = [as_of_date]
    q += " GROUP BY s.match_id, s.team"
    rows = conn.execute(q, args).fetchall()

    # agrupar por match para derivar xGF (propio) y xGA (rival)
    by_match: dict = {}
    for mid, team, xg in rows:
        by_match.setdefault(mid, []).append((team, xg or 0.0))
    xgf, xga, nm = {}, {}, {}
    for mid, lst in by_match.items():
        if len(lst) != 2:
            continue
        (ta, xa), (tb, xb) = lst
        for t, f, a in ((ta, xa, xb), (tb, xb, xa)):
            xgf[t] = xgf.get(t, 0.0) + f
            xga[t] = xga.get(t, 0.0) + a
            nm[t] = nm.get(t, 0) + 1

    ratings = elo.get_ratings(conn)
    ranks = elo.get_ranks(conn)
    # promedio xG por partido del torneo (para normalizar)
    avg_xgf = np.mean([xgf[t] / nm[t] for t in nm]) if nm else 1.0
    now = dt.datetime.now(dt.timezone.utc).isoformat()

    feats = []
    teams = set(ratings) | set(nm)
    for t in teams:
        n = nm.get(t, 0)
        f = xgf.get(t, 0.0) / n if n else None
        a = xga.get(t, 0.0) / n if n else None
        base = ratings.get(t)
        # ajuste de forma por xG del torneo (acotado); requiere base Elo
        eff = base
        if base is not None and n:
            form = float(np.clip(XG_FORM_K * ((f or 0) - (a or 0)), -XG_FORM_CAP, XG_FORM_CAP))
            eff = base + form
        feats.append((t, run_id, as_of_date, n,
                      f, a,
                      (f / avg_xgf) if f is not None else None,
                      (a / avg_xgf) if a is not None else None,
                      eff, ranks.get(t), now))

    conn.executemany(
        """INSERT OR REPLACE INTO team_features
           (team, run_id, as_of_date, n_matches, xgf_per_match, xga_per_match,
            att_strength, def_strength, elo_rating, elo_rank, generated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""", feats)
    conn.commit()
    return {"teams": len(feats), "with_xg": sum(1 for _ in nm)}


def effective_ratings(conn, run_id: str) -> dict:
    """team → Elo efectivo (con ajuste de forma) del run; fallback a Elo base."""
    eff = {t: r for t, r in conn.execute(
        "SELECT team, elo_rating FROM team_features WHERE run_id=? AND elo_rating IS NOT NULL",
        (run_id,))}
    for t, r in elo.get_ratings(conn).items():
        eff.setdefault(t, r)
    return eff
