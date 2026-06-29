"""Orquestador re-ejecutable de la capa de modelo (idempotente).

ensure_xg → ensure_match_model → features → predict → simulate.
Reusa artefactos en models/ si existen; recomputa features/predict/simulate siempre.
"""
from __future__ import annotations

import datetime as dt
import json
import logging

from mova_data.config import RAW_DIR
from mova_data.db import get_db, init_db
from . import xg_model, match_model, strengths, predict as predict_mod, simulate, blend
from .config import N_SIM, SEED

logger = logging.getLogger("mova.pipeline")


def ensure_xg(conn, force=False):
    if xg_model.exists() and not force:
        return xg_model.load()
    from . import shots
    df = shots.from_whoscored(conn)          # nativo WhoScored (con BigChance)
    m, meta = xg_model.train(df)
    meta["source"] = "whoscored"
    xg_model.save(m, meta)
    logger.info("xG entrenado nativo WhoScored (%d tiros)", meta["n_train"])
    return xg_model.load()


def ensure_match_model(conn, force=False):
    if match_model.exists() and not force:
        return match_model.load()
    p = match_model.fit(conn)
    match_model.save(p)
    logger.info("motor de partido calibrado: %s", {k: round(v, 3) if isinstance(v, float) else v for k, v in p.items()})
    return p


def run(as_of=None, n_sims=N_SIM, seed=SEED, retrain=False, run_id=None, w_market=0.65) -> dict:
    init_db()
    run_id = run_id or dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S")
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    w = blend.get_w()

    with get_db() as conn:
        model, xmeta = ensure_xg(conn, force=retrain)
        params = ensure_match_model(conn, force=retrain)
        # features
        n_shots = strengths.apply_xg(conn, model, xmeta["version"])
        finfo = strengths.compute_team_features(conn, run_id, as_of)
        eff = strengths.effective_ratings(conn, run_id)
        logger.info("features: %d tiros xG, %d equipos", n_shots, finfo["teams"])
        # predict
        pinfo = predict_mod.run(conn, run_id, params, eff, w)
        logger.info("predict: %d partidos (%d con mercado)", pinfo["predicted"], pinfo["with_market"])
        # simulate (DP exacto) + anclaje al mercado + congelar resultados ya jugados
        from .market import p_market_winner
        mkt_champ = p_market_winner(conn)
        decided = simulate.decided_matches(conn)
        anc_ratings, _ = simulate.anchor_to_market(conn, eff, params, mkt_champ,
                                                   w=w_market, decided=decided)
        probs = simulate.run_dp(conn, anc_ratings, params, decided)
        simulate.write(conn, run_id, probs, n_sims=0, seed=seed, method="dp+anchor")
        logger.info("simulate: %d equipos (DP anclado w=%.2f, %d partidos congelados)",
                    len(probs), w_market, len(decided))
        # insight (más allá de la fuerza): valor vs mercado, suerte/regresión, camino
        from . import insight
        from .config import OUTPUTS_DIR
        OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
        rep = insight.report(conn, run_id)
        (OUTPUTS_DIR / f"insight_{run_id}.md").write_text(rep)
        (OUTPUTS_DIR / "insight_latest.md").write_text(rep)
        # registro
        conn.execute(
            """INSERT OR REPLACE INTO model_runs
               (run_id, started_at, finished_at, barrier_date, xg_version, dc_version,
                w_blend, n_sims, seed, n_matches_pred, stages, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (run_id, started, dt.datetime.now(dt.timezone.utc).isoformat(), as_of,
             xmeta.get("version"), f"b0={params['b0']:.3f},rho={params['rho']:.3f}",
             w, n_sims, seed, pinfo["predicted"],
             json.dumps(["xg", "match_model", "features", "predict", "simulate"]), "ok"))
        conn.commit()
    return {"run_id": run_id, "shots": n_shots, **pinfo, "teams_sim": len(probs)}
