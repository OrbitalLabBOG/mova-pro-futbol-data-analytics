"""Hyperparameter grid tuning on 2023-24 and 2024-25 (prior = previous season).

Tunes strictly out-of-time by Poisson deviance conditional on minutes > 0.
Never touches 2025-26 or 2026-27.
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import mean_poisson_deviance

from experiments.recency_eb.data import (
    build_results,
    build_roster,
    causal_history,
    load_frozen_models,
    load_vaastav_season,
    make_eb_points_model,
)
from mova_fpl.models.features.points_features import RecencyEBConfig, normaliza_posicion

DEV_PAIRS = (("2022-23", "2023-24"), ("2023-24", "2024-25"))
H_ATK_GRID = (6.0, 8.0, 10.0)
K_ATK_GRID = (5.0, 6.0, 8.0)
H_ROLE_GRID = (4.0, 6.0)
K_ROLE_GRID = (3.0, 4.0)
N_CAP = 15.0
GAMMA_CLUB = 0.7


def _poisson_dev(actual: np.ndarray, expected: np.ndarray) -> float:
    y = np.clip(np.asarray(actual, dtype=float), 0.0, None)
    mu = np.clip(np.asarray(expected, dtype=float), 1e-6, None)
    return float(mean_poisson_deviance(y, mu))


def _collect_rate_eval(prev_df: pd.DataFrame, curr_df: pd.DataFrame,
                       points_model, *, eval_gws: range = range(1, 39)) -> dict[str, float]:
    """Walk-forward out-of-time rate evaluation conditional on minutes > 0."""
    goals_y, goals_mu = [], []
    assists_y, assists_mu = [], []
    xg_y, xg_mu = [], []
    xa_y, xa_mu = [], []
    bps_y, bps_mu = [], []
    bonus_y, bonus_mu = [], []
    n_rows = 0

    for gw in eval_gws:
        roster = build_roster(curr_df, gw)
        actual = build_results(curr_df, gw)
        if roster.empty or actual.empty:
            continue
        hist = causal_history(prev_df, curr_df, gw)
        truth = actual.groupby("element", as_index=False).agg(
            minutes=("minutes", "sum"),
            goals_scored=("goals_scored", "sum"),
            assists=("assists", "sum"),
            expected_goals=("expected_goals", "sum"),
            expected_assists=("expected_assists", "sum"),
            bps=("bps", "sum"),
            bonus=("bonus", "sum"),
            n_apps=("minutes", lambda s: int((pd.to_numeric(s, errors="coerce").fillna(0) > 0).sum())),
        )
        merged = roster[["element"]].merge(truth, on="element", how="left").fillna(0.0)
        expo = merged["minutes"].to_numpy(dtype=float) / 90.0
        played = expo > 0.0
        if not played.any():
            continue

        pos = normaliza_posicion(roster["position"]).fillna("MID")
        state = points_model.player_state(hist, roster)

        # Attack rates (both blended goals/assists via GoalsModel and raw xg90/xa90)
        rate_g = points_model.goals.rate(state, pos, "gol")
        rate_a = points_model.goals.rate(state, pos, "asistencia")
        xg90 = np.clip(pd.to_numeric(state["xg90"], errors="coerce").fillna(0.0).to_numpy(float), 0.0, None)
        xa90 = np.clip(pd.to_numeric(state["xa90"], errors="coerce").fillna(0.0).to_numpy(float), 0.0, None)
        bps90 = np.clip(pd.to_numeric(state["bps90"], errors="coerce").fillna(0.0).to_numpy(float), 0.0, None)
        bon_app = np.clip(pd.to_numeric(state["bonus_aparicion"], errors="coerce").fillna(0.0).to_numpy(float), 0.0, None)

        e = expo[played]
        apps = np.clip(merged["n_apps"].to_numpy(dtype=float)[played], 1.0, None)
        n_rows += int(played.sum())

        goals_y.append(merged["goals_scored"].to_numpy(float)[played])
        goals_mu.append(rate_g[played] * e)
        assists_y.append(merged["assists"].to_numpy(float)[played])
        assists_mu.append(rate_a[played] * e)
        xg_y.append(merged["expected_goals"].to_numpy(float)[played])
        xg_mu.append(xg90[played] * e)
        xa_y.append(merged["expected_assists"].to_numpy(float)[played])
        xa_mu.append(xa90[played] * e)
        bps_y.append(merged["bps"].to_numpy(float)[played])
        bps_mu.append(bps90[played] * e)
        bonus_y.append(merged["bonus"].to_numpy(float)[played])
        bonus_mu.append(bon_app[played] * apps)

    gy, gmu = np.concatenate(goals_y), np.concatenate(goals_mu)
    ay, amu = np.concatenate(assists_y), np.concatenate(assists_mu)
    xgy, xgmu = np.concatenate(xg_y), np.concatenate(xg_mu)
    xay, xamu = np.concatenate(xa_y), np.concatenate(xa_mu)
    by, bmu = np.concatenate(bps_y), np.concatenate(bps_mu)
    bny, bnmu = np.concatenate(bonus_y), np.concatenate(bonus_mu)

    dev_xg = _poisson_dev(xgy, xgmu)
    dev_xa = _poisson_dev(xay, xamu)
    dev_g = _poisson_dev(gy, gmu)
    dev_a = _poisson_dev(ay, amu)
    dev_bps = _poisson_dev(np.clip(by, 0.0, None), bmu)
    dev_bonus = _poisson_dev(bny, bnmu)

    return {
        "n_played_rows": n_rows,
        "dev_xg": round(dev_xg, 6),
        "dev_xa": round(dev_xa, 6),
        "dev_attack_xg_xa": round(0.5 * (dev_xg + dev_xa), 6),
        "dev_goals": round(dev_g, 6),
        "dev_assists": round(dev_a, 6),
        "dev_attack_g_a": round(0.5 * (dev_g + dev_a), 6),
        "dev_bps": round(dev_bps, 6),
        "dev_bonus": round(dev_bonus, 6),
        "dev_role_bps_bonus": round(0.5 * (dev_bps + dev_bonus), 6),
        "bps_mae": round(float(np.mean(np.abs(by - bmu))), 4),
        "xg_bias_sum": round(float(np.sum(xgmu) - np.sum(xgy)), 2),
        "xa_bias_sum": round(float(np.sum(xamu) - np.sum(xay)), 2),
        "bps_bias_sum": round(float(np.sum(bmu) - np.sum(by)), 2),
    }


def run_tune(verbose: bool = True) -> dict[str, Any]:
    """Run grid search on 2023-24 and 2024-25 and freeze the winning (H, K) config."""
    t0 = time.perf_counter()
    _, points_prod = load_frozen_models()

    seasons_data = {}
    for prev_s, curr_s in DEV_PAIRS:
        if prev_s not in seasons_data:
            seasons_data[prev_s] = load_vaastav_season(prev_s)
        if curr_s not in seasons_data:
            seasons_data[curr_s] = load_vaastav_season(curr_s)

    # Baseline 1.1.0 reference on the exact same dev folds
    baseline_by_season = {}
    for prev_s, curr_s in DEV_PAIRS:
        baseline_by_season[curr_s] = _collect_rate_eval(
            seasons_data[prev_s], seasons_data[curr_s], points_prod,
        )
    baseline_mean = {
        "dev_attack_xg_xa": round(float(np.mean([v["dev_attack_xg_xa"] for v in baseline_by_season.values()])), 6),
        "dev_attack_g_a": round(float(np.mean([v["dev_attack_g_a"] for v in baseline_by_season.values()])), 6),
        "dev_bps": round(float(np.mean([v["dev_bps"] for v in baseline_by_season.values()])), 6),
        "dev_bonus": round(float(np.mean([v["dev_bonus"] for v in baseline_by_season.values()])), 6),
        "dev_role_bps_bonus": round(float(np.mean([v["dev_role_bps_bonus"] for v in baseline_by_season.values()])), 6),
    }
    if verbose:
        print(f"[tune] Baseline 1.1.0 dev mean: {baseline_mean}", flush=True)

    # Attack family grid (9 combos — mathematically independent of role family)
    attack_table = []
    for h_atk in H_ATK_GRID:
        for k_atk in K_ATK_GRID:
            cfg = RecencyEBConfig(
                h_attack=h_atk, k_in_attack=k_atk,
                h_role=4.0, k_in_role=3.0,
                n_cap=N_CAP, gamma_club=GAMMA_CLUB,
            )
            cand = make_eb_points_model(points_prod, cfg)
            by_s = {}
            for prev_s, curr_s in DEV_PAIRS:
                by_s[curr_s] = _collect_rate_eval(seasons_data[prev_s], seasons_data[curr_s], cand)
            mean_xg_xa = float(np.mean([v["dev_attack_xg_xa"] for v in by_s.values()]))
            mean_g_a = float(np.mean([v["dev_attack_g_a"] for v in by_s.values()]))
            row = {
                "h_attack": h_atk,
                "k_in_attack": k_atk,
                "k_in_newcomer_attack": cfg.effective_k_in_newcomer_attack,
                "mean_dev_xg_xa": round(mean_xg_xa, 6),
                "mean_dev_g_a": round(mean_g_a, 6),
                "by_season": {
                    s: {k: by_s[s][k] for k in ("dev_xg", "dev_xa", "dev_attack_xg_xa", "dev_goals", "dev_assists", "dev_attack_g_a", "xg_bias_sum", "xa_bias_sum")}
                    for s in by_s
                },
            }
            attack_table.append(row)
            if verbose:
                print(f"[tune][atk] H={h_atk:>4.1f} K={k_atk:>3.1f} -> xg_xa_dev={mean_xg_xa:.6f} g_a_dev={mean_g_a:.6f}", flush=True)

    attack_table.sort(key=lambda r: r["mean_dev_xg_xa"])
    best_atk = attack_table[0]

    # Role family grid (4 combos — independent of attack family)
    role_table = []
    for h_role in H_ROLE_GRID:
        for k_role in K_ROLE_GRID:
            cfg = RecencyEBConfig(
                h_attack=best_atk["h_attack"], k_in_attack=best_atk["k_in_attack"],
                h_role=h_role, k_in_role=k_role,
                n_cap=N_CAP, gamma_club=GAMMA_CLUB,
            )
            cand = make_eb_points_model(points_prod, cfg)
            by_s = {}
            for prev_s, curr_s in DEV_PAIRS:
                by_s[curr_s] = _collect_rate_eval(seasons_data[prev_s], seasons_data[curr_s], cand)
            mean_bps = float(np.mean([v["dev_bps"] for v in by_s.values()]))
            mean_bonus = float(np.mean([v["dev_bonus"] for v in by_s.values()]))
            mean_role = float(np.mean([v["dev_role_bps_bonus"] for v in by_s.values()]))
            mean_bps_mae = float(np.mean([v["bps_mae"] for v in by_s.values()]))
            row = {
                "h_role": h_role,
                "k_in_role": k_role,
                "k_in_newcomer_role": cfg.effective_k_in_newcomer_role,
                "mean_dev_bps": round(mean_bps, 6),
                "mean_dev_bonus": round(mean_bonus, 6),
                "mean_dev_role_bps_bonus": round(mean_role, 6),
                "mean_bps_mae": round(mean_bps_mae, 4),
                "by_season": {
                    s: {k: by_s[s][k] for k in ("dev_bps", "dev_bonus", "dev_role_bps_bonus", "bps_mae", "bps_bias_sum")}
                    for s in by_s
                },
            }
            role_table.append(row)
            if verbose:
                print(f"[tune][role] H={h_role:>4.1f} K={k_role:>3.1f} -> bps_dev={mean_bps:.6f} bonus_dev={mean_bonus:.6f} role_dev={mean_role:.6f}", flush=True)

    role_table.sort(key=lambda r: (r["mean_bps_mae"], r["mean_dev_role_bps_bonus"]))
    best_role = role_table[0]

    winner_cfg = RecencyEBConfig(
        h_attack=best_atk["h_attack"],
        k_in_attack=best_atk["k_in_attack"],
        h_role=best_role["h_role"],
        k_in_role=best_role["k_in_role"],
        n_cap=N_CAP,
        gamma_club=GAMMA_CLUB,
    )

    elapsed = round(time.perf_counter() - t0, 2)
    if verbose:
        print(f"[tune] FROZEN WINNER ({elapsed}s): H_atk={winner_cfg.h_attack}, K_in_atk={winner_cfg.k_in_attack}, "
              f"H_role={winner_cfg.h_role}, K_in_role={winner_cfg.k_in_role}, "
              f"N_cap={winner_cfg.n_cap}, gamma_club={winner_cfg.gamma_club}", flush=True)

    return {
        "source": "grid_2023_24_and_2024_25",
        "dev_seasons": ["2023-24", "2024-25"],
        "criterion": "attack: mean OOT Poisson deviance of xG+xA (minutes>0); role: mean BPS MAE (primary) with Poisson-on-clipped-BPS as diagnostic only",
        "runtime_seconds": elapsed,
        "baseline_1_1_0": {
            "mean": baseline_mean,
            "by_season": baseline_by_season,
        },
        "attack_grid": attack_table,
        "role_grid": role_table,
        "winner": {
            "h_attack": winner_cfg.h_attack,
            "k_in_attack": winner_cfg.k_in_attack,
            "k_in_newcomer_attack": winner_cfg.effective_k_in_newcomer_attack,
            "h_role": winner_cfg.h_role,
            "k_in_role": winner_cfg.k_in_role,
            "k_in_newcomer_role": winner_cfg.effective_k_in_newcomer_role,
            "n_cap": winner_cfg.n_cap,
            "gamma_club": winner_cfg.gamma_club,
            "skip_bonus_double_shrink": winner_cfg.skip_bonus_double_shrink,
        },
    }
