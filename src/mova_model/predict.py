"""Genera match_predictions: 1X2 modelo + mercado + blend para cada partido del torneo."""
from __future__ import annotations

import datetime as dt

from mova_data.teams import resolve
from . import elo, match_model, market, blend


def _home_away(conn, oddsapi_event_id, whoscored_id, espn_id, team_a, team_b):
    """Orientación home/away canónica desde la mejor fuente (alineada con el mercado)."""
    if oddsapi_event_id:
        r = conn.execute("SELECT home_team, away_team FROM odds_quotes WHERE event_id=? LIMIT 1",
                         (oddsapi_event_id,)).fetchone()
        if r:
            return resolve(conn, r[0]) or r[0], resolve(conn, r[1]) or r[1]
    if whoscored_id:
        r = conn.execute("SELECT home_team, away_team FROM matches WHERE match_id=?",
                         (whoscored_id,)).fetchone()
        if r:
            return resolve(conn, r[0]) or r[0], resolve(conn, r[1]) or r[1]
    if espn_id:
        r = conn.execute("SELECT home_team, away_team FROM espn_fixtures WHERE espn_id=?",
                         (espn_id,)).fetchone()
        if r:
            return resolve(conn, r[0]) or r[0], resolve(conn, r[1]) or r[1]
    return team_a, team_b


def run(conn, run_id: str, params: dict, eff_ratings: dict, w: float) -> dict:
    rows = conn.execute(
        """SELECT match_key, team_a, team_b, match_date, whoscored_id, espn_id, oddsapi_event_id
           FROM match_map""").fetchall()
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    out = []
    n_mkt = 0
    for mk, ta, tb, mdate, wsid, espnid, oaid in rows:
        home, away = _home_away(conn, oaid, wsid, espnid, ta, tb)
        rh, ra = eff_ratings.get(home), eff_ratings.get(away)
        if rh is None or ra is None:
            continue
        dr = elo.dr(rh, ra, neutral=True)
        pm = match_model.predict_1x2(dr, params)             # (H,D,A) modelo
        mk_probs = market.p_market_1x2(conn, oaid)           # (H,D,A) mercado o None
        nq = 0
        if mk_probs:
            n_mkt += 1
            nq = conn.execute("SELECT count(*) FROM odds_quotes WHERE scope='match' AND event_id=?",
                              (oaid,)).fetchone()[0]
            final = tuple(blend.log_pool(pm, mk_probs, w))
        else:
            final = pm
        out.append((mk, run_id, home, away, mdate,
                    *(None, None),                            # lambdas (opcional, no guardamos aquí)
                    *pm, *(mk_probs or (None, None, None)), *final, w, nq, now))
    conn.executemany(
        """INSERT OR REPLACE INTO match_predictions
           (match_key, run_id, home_team, away_team, match_date, lambda_home, lambda_away,
            p_home_model, p_draw_model, p_away_model, p_home_mkt, p_draw_mkt, p_away_mkt,
            p_home, p_draw, p_away, w_blend, n_quotes, generated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", out)
    conn.commit()
    return {"predicted": len(out), "with_market": n_mkt}
