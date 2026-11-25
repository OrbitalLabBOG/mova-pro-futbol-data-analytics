"""Walk-forward prediction evaluation for 2025-26 and 2026-27 (frozen Minutes 1.1.0)."""
from __future__ import annotations

import time
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from experiments.recency_eb.data import (
    build_results,
    build_roster,
    causal_history,
)
from mova_fpl.engine.projection import _proba_minutos
from mova_fpl.models.points import COMPONENTES
from mova_fpl.rules import get as get_rules


def compute_slice_metrics(pred: pd.Series, actual: pd.Series) -> dict[str, Any]:
    mask = pred.notna() & actual.notna()
    p = pred[mask].to_numpy(dtype=float)
    a = actual[mask].to_numpy(dtype=float)
    n = int(len(p))
    if n < 5:
        return {"n": n}
    pred_sum = float(np.sum(p))
    actual_sum = float(np.sum(a))
    bias_sum = pred_sum - actual_sum
    bias_rel_pct = (100.0 * bias_sum / actual_sum) if abs(actual_sum) > 1e-9 else None
    sp = float(spearmanr(p, a).correlation) if np.std(p) > 0 and np.std(a) > 0 else float("nan")
    return {
        "n": n,
        "mae": round(float(np.mean(np.abs(p - a))), 4),
        "rmse": round(float(np.sqrt(np.mean((p - a) ** 2))), 4),
        "spearman": round(sp, 4) if np.isfinite(sp) else None,
        "bias_sum": round(bias_sum, 2),
        "bias_rel_pct": round(bias_rel_pct, 2) if bias_rel_pct is not None else None,
        "pred_sum": round(pred_sum, 2),
        "actual_sum": round(actual_sum, 2),
    }


def _captaincy_regret(frame: pd.DataFrame) -> dict[str, Any]:
    """Paired captaincy metrics on realistic pool (xp >= 4.5 or top-15 xP per GW)."""
    top1_pts, top2_blend_pts, pool_best_pts, regrets = [], [], [], []
    for _, sub in frame.groupby("gw"):
        s = sub.dropna(subset=["xp", "actual"]).sort_values("xp", ascending=False)
        if len(s) < 2:
            continue
        pool = s[s["xp"] >= 4.5]
        if len(pool) < 5:
            pool = s.head(15)
        c1 = float(s.iloc[0]["actual"])
        c2 = float(s.iloc[1]["actual"])
        best_pool = float(pool["actual"].max())
        top1_pts.append(c1)
        top2_blend_pts.append(0.7 * c1 + 0.3 * c2)
        pool_best_pts.append(best_pool)
        regrets.append(best_pool - c1)
    if not top1_pts:
        return {"gws": 0}
    return {
        "gws": len(top1_pts),
        "top1_actual_sum": round(float(np.sum(top1_pts)), 2),
        "top1_actual_mean": round(float(np.mean(top1_pts)), 3),
        "blend_07_03_sum": round(float(np.sum(top2_blend_pts)), 2),
        "pool_best_sum": round(float(np.sum(pool_best_pts)), 2),
        "mean_regret_vs_pool_best": round(float(np.mean(regrets)), 3),
    }


def summarize_prediction_frame(frame: pd.DataFrame) -> dict[str, Any]:
    """Compute standardized slices, component sums, and captaincy diagnostics."""
    eligible = frame[(frame["p_play"] >= 0.25) | (frame["price"] >= 5.0)]
    played = frame[frame["minutes"] > 0]
    min60 = frame[frame["minutes"] >= 60]
    premiums = frame[frame["price"] >= 8.0]
    prem_elig = eligible[eligible["price"] >= 8.0]

    comp_sums = {
        c: round(float(frame[c].sum()), 2)
        for c in COMPONENTES if c in frame.columns
    }
    comp_sums_min60 = {
        c: round(float(min60[c].sum()), 2)
        for c in COMPONENTES if c in min60.columns
    }
    return {
        "all": compute_slice_metrics(frame["xp"], frame["actual"]),
        "eligible_p25_or_5m": compute_slice_metrics(eligible["xp"], eligible["actual"]),
        "minutes_gt_0": compute_slice_metrics(played["xp"], played["actual"]),
        "minutes_ge_60": compute_slice_metrics(min60["xp"], min60["actual"]),
        "premiums_ge_8m": compute_slice_metrics(premiums["xp"], premiums["actual"]),
        "premiums_eligible": compute_slice_metrics(prem_elig["xp"], prem_elig["actual"]),
        "captaincy": _captaincy_regret(frame),
        "component_sums_all": comp_sums,
        "component_sums_min60": comp_sums_min60,
    }


def player_diagnostics(frame: pd.DataFrame, targets: dict[int, str]) -> dict[str, Any]:
    """Named player residual diagnostics (diagnostic only, NEVER a gate)."""
    out = {}
    for el, label in targets.items():
        sub = frame[frame["element"] == int(el)].sort_values("gw")
        if sub.empty:
            out[label] = {"element": int(el), "n": 0}
            continue
        out[label] = {
            "element": int(el),
            "n": int(len(sub)),
            "xp_sum": round(float(sub["xp"].sum()), 2),
            "actual_sum": int(sub["actual"].sum()),
            "residual_pred_minus_actual": round(float(sub["xp"].sum() - sub["actual"].sum()), 2),
            "by_gw": [
                {
                    "gw": int(r.gw),
                    "xp": round(float(r.xp), 2),
                    "actual": int(r.actual),
                    "minutes": int(r.minutes),
                    "p_play": round(float(r.p_play), 3),
                }
                for r in sub.itertuples(index=False)
            ],
        }
    return out


def evaluate_walkforward_predictions(
    *,
    season: str,
    prev_df: pd.DataFrame,
    curr_df: pd.DataFrame,
    equipos: dict[int, str],
    minutes_model,
    points_control,
    points_candidate,
    gws: list[int],
    catalog_asof: pd.DataFrame | None = None,
    verbose: bool = True,
) -> dict[str, Any]:
    """Run paired walk-forward prediction evaluation using identical frozen Minutes 1.1.0."""
    t0 = time.perf_counter()
    scoring = get_rules(season).SCORING
    umbrales = scoring.defcon_thresholds

    ep_lookup = None
    if catalog_asof is not None and not catalog_asof.empty:
        ep_lookup = catalog_asof[["target_gw", "element", "ep_next"]].copy()
        ep_lookup["target_gw"] = pd.to_numeric(ep_lookup["target_gw"], errors="coerce").astype(int)
        ep_lookup["element"] = pd.to_numeric(ep_lookup["element"], errors="coerce").astype(int)
        ep_lookup["ep_next"] = pd.to_numeric(ep_lookup["ep_next"], errors="coerce")

    rows_ctrl, rows_cand = [], []
    for gw in gws:
        roster = build_roster(curr_df, gw)
        actual = build_results(curr_df, gw)
        if roster.empty or actual.empty:
            continue
        hist = causal_history(prev_df, curr_df, gw)

        # Identical frozen Minutes 1.1.0 probabilities for BOTH arms
        proba = _proba_minutos(hist, roster, minutes_model)
        p_play = proba[:, 1] + proba[:, 2]
        p_60 = proba[:, 2]

        truth = actual.groupby("element", as_index=False).agg(
            actual=("total_points", "sum"),
            minutes=("minutes", "sum"),
        )
        base_meta = roster[["element", "player_key", "name", "position", "team", "value"]].copy()
        base_meta["gw"] = int(gw)
        base_meta["price"] = pd.to_numeric(base_meta["value"], errors="coerce") / 10.0
        base_meta["p_play"] = p_play
        base_meta["p_60"] = p_60
        base_meta = base_meta.merge(truth, on="element", how="left")
        base_meta["actual"] = base_meta["actual"].fillna(0).astype(int)
        base_meta["minutes"] = base_meta["minutes"].fillna(0).astype(int)

        if ep_lookup is not None:
            ep_gw = ep_lookup[ep_lookup["target_gw"] == int(gw)][["element", "ep_next"]]
            base_meta = base_meta.merge(ep_gw, on="element", how="left")
        else:
            base_meta["ep_next"] = np.nan

        for arm_rows, pm in ((rows_ctrl, points_control), (rows_cand, points_candidate)):
            pred = pm.project(hist, roster, proba, scoring, umbrales, equipos=equipos)
            f = base_meta.copy()
            f["xp"] = pred["xp"].to_numpy(dtype=float)
            f["xp_sd"] = pred["xp_sd"].to_numpy(dtype=float)
            for c in COMPONENTES:
                f[c] = pred[c].to_numpy(dtype=float)
            arm_rows.append(f)

    df_ctrl = pd.concat(rows_ctrl, ignore_index=True)
    df_cand = pd.concat(rows_cand, ignore_index=True)

    res: dict[str, Any] = {
        "season": season,
        "gws": [int(g) for g in gws],
        "runtime_seconds": round(time.perf_counter() - t0, 2),
        "control_1_1_0": summarize_prediction_frame(df_ctrl),
        "candidate_1_2_0_eb": summarize_prediction_frame(df_cand),
    }

    # Subwindow breakdown for 2026-27 (GW2-6 vs GW7-11) and ep_next comparison on GW8-11
    if season == "2026-27":
        res["subwindows"] = {}
        for label, lo, hi in (("gw2_6", 2, 6), ("gw7_11", 7, 11), ("gw8_11", 8, 11)):
            sc = df_ctrl[(df_ctrl["gw"] >= lo) & (df_ctrl["gw"] <= hi)]
            se = df_cand[(df_cand["gw"] >= lo) & (df_cand["gw"] <= hi)]
            if not sc.empty:
                entry = {
                    "control_1_1_0": summarize_prediction_frame(sc),
                    "candidate_1_2_0_eb": summarize_prediction_frame(se),
                }
                if sc["ep_next"].notna().any():
                    ep_elig = sc[(sc["p_play"] >= 0.25) | (sc["price"] >= 5.0)]
                    ep_played = sc[sc["minutes"] > 0]
                    entry["ep_next_pre_deadline"] = {
                        "all": compute_slice_metrics(sc["ep_next"], sc["actual"]),
                        "eligible_p25_or_5m": compute_slice_metrics(ep_elig["ep_next"], ep_elig["actual"]),
                        "minutes_gt_0": compute_slice_metrics(ep_played["ep_next"], ep_played["actual"]),
                    }
                res["subwindows"][label] = entry

        diag_targets = {426: "Bruno (426)", 427: "Mbeumo (427)", 411: "Haaland (411)"}
        res["diagnostics_named_players_not_gate"] = {
            "gw2_11": {
                "control_1_1_0": player_diagnostics(df_ctrl, diag_targets),
                "candidate_1_2_0_eb": player_diagnostics(df_cand, diag_targets),
            },
            "gw8_11": {
                "control_1_1_0": player_diagnostics(df_ctrl[df_ctrl["gw"] >= 8], diag_targets),
                "candidate_1_2_0_eb": player_diagnostics(df_cand[df_cand["gw"] >= 8], diag_targets),
            },
        }

    if verbose:
        c_el = res["control_1_1_0"]["eligible_p25_or_5m"]
        e_el = res["candidate_1_2_0_eb"]["eligible_p25_or_5m"]
        print(
            f"[eval {season} GW{min(gws)}-{max(gws)}] eligible MAE: 1.1.0={c_el['mae']} vs eb2={e_el['mae']} | "
            f"Spearman: {c_el['spearman']} vs {e_el['spearman']} | "
            f"Bias%: {c_el['bias_rel_pct']}% vs {e_el['bias_rel_pct']}% ({res['runtime_seconds']}s)",
            flush=True,
        )
    return res


def evaluate_gw8_11_sealed_minutes(
    *,
    prev_df: pd.DataFrame,
    curr_df: pd.DataFrame,
    equipos: dict[int, str],
    proj_approved: pd.DataFrame,
    catalog_asof: pd.DataFrame,
    fixtures: pd.DataFrame,
    points_control,
    points_candidate,
) -> dict[str, Any]:
    """Secondary check holding p0/p1/p60 fixed to the sealed VPS approved batch (GW8-11)."""
    scoring = get_rules("2026-27").SCORING
    umbrales = scoring.defcon_thresholds
    rows_ctrl, rows_cand = [], []

    for gw in (8, 9, 10, 11):
        roster = build_roster(curr_df, gw)
        actual = build_results(curr_df, gw)
        hist = causal_history(prev_df, curr_df, gw)

        gproj = proj_approved[proj_approved["gw"] == gw][
            ["element", "xp", "p_play", "p_60"]
        ].rename(columns={"xp": "xp_sealed_prod"})
        ep_gw = catalog_asof[catalog_asof["target_gw"] == gw][["element", "ep_next"]].copy()
        ep_gw["ep_next"] = pd.to_numeric(ep_gw["ep_next"], errors="coerce")

        r = roster.merge(gproj, on="element", how="inner").merge(ep_gw, on="element", how="left")
        truth = actual.groupby("element", as_index=False).agg(
            actual=("total_points", "sum"),
            minutes=("minutes", "sum"),
        )
        r = r.merge(truth, on="element", how="left")
        r["actual"] = r["actual"].fillna(0).astype(int)
        r["minutes"] = r["minutes"].fillna(0).astype(int)
        r["price"] = pd.to_numeric(r["value"], errors="coerce") / 10.0

        p60 = pd.to_numeric(r["p_60"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
        p_play = pd.to_numeric(r["p_play"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
        p1 = np.clip(p_play - p60, 0.0, 1.0)
        p0 = np.clip(1.0 - p_play, 0.0, 1.0)
        proba = np.column_stack([p0, p1, p60])

        for arm_rows, pm in ((rows_ctrl, points_control), (rows_cand, points_candidate)):
            pred = pm.project(hist, r, proba, scoring, umbrales, equipos=equipos)
            f = r[["element", "name", "position", "team", "gw", "price", "p_play", "p_60",
                   "actual", "minutes", "ep_next", "xp_sealed_prod"]].copy()
            f["xp"] = pred["xp"].to_numpy(dtype=float)
            for c in COMPONENTES:
                f[c] = pred[c].to_numpy(dtype=float)
            arm_rows.append(f)

    df_ctrl = pd.concat(rows_ctrl, ignore_index=True)
    df_cand = pd.concat(rows_cand, ignore_index=True)

    repro_mae = float(np.mean(np.abs(df_ctrl["xp"] - df_ctrl["xp_sealed_prod"])))
    repro_corr = float(np.corrcoef(df_ctrl["xp"], df_ctrl["xp_sealed_prod"])[0, 1])

    diag_targets = {426: "Bruno (426)", 427: "Mbeumo (427)", 411: "Haaland (411)"}
    return {
        "note": "Fixed p0/p1/p60 from sealed VPS approved batch (includes pre-deadline medical availability)",
        "control_vs_sealed_prod_batch": {
            "mae": round(repro_mae, 4),
            "corr": round(repro_corr, 4),
        },
        "sealed_prod_batch": summarize_prediction_frame(
            df_ctrl.drop(columns=["xp"]).rename(columns={"xp_sealed_prod": "xp"})
        ),
        "control_1_1_0": summarize_prediction_frame(df_ctrl),
        "candidate_1_2_0_eb": summarize_prediction_frame(df_cand),
        "ep_next_pre_deadline": {
            "all": compute_slice_metrics(df_ctrl["ep_next"], df_ctrl["actual"]),
            "eligible_p25_or_5m": compute_slice_metrics(
                df_ctrl[(df_ctrl["p_play"] >= 0.25) | (df_ctrl["price"] >= 5.0)]["ep_next"],
                df_ctrl[(df_ctrl["p_play"] >= 0.25) | (df_ctrl["price"] >= 5.0)]["actual"],
            ),
            "minutes_gt_0": compute_slice_metrics(
                df_ctrl[df_ctrl["minutes"] > 0]["ep_next"],
                df_ctrl[df_ctrl["minutes"] > 0]["actual"],
            ),
        },
        "diagnostics_named_players_not_gate": {
            "control_1_1_0": player_diagnostics(df_ctrl, diag_targets),
            "candidate_1_2_0_eb": player_diagnostics(df_cand, diag_targets),
        },
    }
