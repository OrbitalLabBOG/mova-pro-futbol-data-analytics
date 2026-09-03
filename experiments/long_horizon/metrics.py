"""Métricas de pronóstico y valor de política para experimentos pareados."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy.special import ndtr
from scipy.stats import spearmanr


def normal_crps(actual, mean, sd) -> np.ndarray:
    """CRPS de una Normal; ``sd=0`` degenera en error absoluto."""
    y = np.asarray(actual, dtype=float)
    mu = np.asarray(mean, dtype=float)
    sigma = np.asarray(sd, dtype=float)
    out = np.abs(y - mu)
    valid = np.isfinite(sigma) & (sigma > 1e-9)
    z = (y[valid] - mu[valid]) / sigma[valid]
    phi = np.exp(-0.5 * z ** 2) / math.sqrt(2.0 * math.pi)
    out[valid] = sigma[valid] * (
        z * (2.0 * ndtr(z) - 1.0) + 2.0 * phi - 1.0 / math.sqrt(math.pi)
    )
    return out


def predictive_metrics(frame: pd.DataFrame) -> dict:
    """Evalúa media, ranking y cobertura de la distribución jugador-GW."""
    d = frame.dropna(subset=["actual", "xp", "xp_sd"]).copy()
    y, mu, sd = (d[c].to_numpy(dtype=float) for c in ("actual", "xp", "xp_sd"))
    z = np.divide(y - mu, sd, out=np.full_like(y, np.nan), where=sd > 1e-9)
    rank = spearmanr(y, mu).statistic if len(d) > 2 else np.nan
    return {
        "rows": int(len(d)),
        "mae": float(np.mean(np.abs(y - mu))),
        "rmse": float(np.sqrt(np.mean((y - mu) ** 2))),
        "crps_normal": float(np.mean(normal_crps(y, mu, sd))),
        "spearman": float(rank) if np.isfinite(rank) else None,
        "bias": float(np.mean(mu - y)),
        "coverage_50": float(np.nanmean(np.abs(z) <= 0.67448975)),
        "coverage_80": float(np.nanmean(np.abs(z) <= 1.28155157)),
        "coverage_90": float(np.nanmean(np.abs(z) <= 1.64485363)),
    }


def _paired_frame(baseline: pd.DataFrame, candidate: pd.DataFrame) -> pd.DataFrame:
    keys = ["season", "gw"]
    for name, frame in (("baseline", baseline), ("candidate", candidate)):
        missing = sorted(set(keys + ["points"]) - set(frame.columns))
        if missing:
            raise ValueError(f"{name} no contiene columnas {missing}")
        if frame.duplicated(keys).any():
            raise ValueError(f"{name} contiene season/GW duplicadas")
    merged = baseline[keys + ["points"]].merge(
        candidate[keys + ["points"]], on=keys, suffixes=("_baseline", "_candidate"),
        how="outer", validate="one_to_one", indicator=True,
    )
    if not (merged["_merge"] == "both").all():
        raise ValueError("control y candidato no tienen exactamente las mismas season/GW")
    merged["delta"] = merged["points_candidate"] - merged["points_baseline"]
    return merged.drop(columns="_merge").sort_values(keys).reset_index(drop=True)


def paired_policy_influence(baseline: pd.DataFrame, candidate: pd.DataFrame) -> dict:
    """Expone cuánto depende PVA de una temporada o una GW extrema.

    No reemplaza el bootstrap. Es un diagnóstico determinista de fragilidad para
    impedir que la media agregada esconda una victoria o derrota de un solo evento.
    """
    merged = _paired_frame(baseline, candidate)
    if merged.empty:
        raise ValueError("no hay jornadas pareadas")
    by_season = {}
    season_totals = {}
    for season, group in merged.groupby("season", sort=True):
        values = group["delta"].to_numpy(dtype=float)
        gameweeks = group["gw"].to_numpy(dtype=int)
        total = float(values.sum())
        worst_at, best_at = int(np.argmin(values)), int(np.argmax(values))
        worst, best = float(values[worst_at]), float(values[best_at])
        absolute_path = float(np.abs(values).sum())
        without_worst, without_best = total - worst, total - best
        key = str(season)
        season_totals[key] = total
        by_season[key] = {
            "gameweeks": int(len(values)),
            "delta": total,
            "through_penultimate_gw": float(values[:-1].sum()) if len(values) > 1 else 0.0,
            "final_gw_delta": float(values[-1]),
            "worst_gw": {"gw": int(gameweeks[worst_at]), "delta": worst},
            "best_gw": {"gw": int(gameweeks[best_at]), "delta": best},
            "delta_without_worst_gw": float(without_worst),
            "delta_without_best_gw": float(without_best),
            "loss_reversal_by_one_gw": bool(total <= 0 < without_worst),
            "win_supported_by_one_gw": bool(total > 0 >= without_best),
            "absolute_delta_path": absolute_path,
            "max_single_gw_share_of_absolute_path": (
                float(np.max(np.abs(values)) / absolute_path) if absolute_path else 0.0
            ),
            "positive_gws": int(np.sum(values > 0)),
            "negative_gws": int(np.sum(values < 0)),
            "tie_gws": int(np.sum(values == 0)),
        }

    totals = np.asarray(list(season_totals.values()), dtype=float)
    leave_one_out = {
        season: float(np.mean([value for other, value in season_totals.items()
                              if other != season]))
        for season in season_totals
    } if len(season_totals) > 1 else {}
    all_values = merged["delta"].to_numpy(dtype=float)
    return {
        "method": "paired_policy_influence_v1",
        "seasons": int(len(totals)),
        "gameweeks": int(len(merged)),
        "season_mean_delta": float(np.mean(totals)),
        "season_median_delta": float(np.median(totals)),
        "season_wins": int(np.sum(totals > 0)),
        "season_losses": int(np.sum(totals < 0)),
        "season_ties": int(np.sum(totals == 0)),
        "leave_one_season_out_mean": leave_one_out,
        "loss_reversal_seasons": [
            season for season, row in by_season.items()
            if row["loss_reversal_by_one_gw"]
        ],
        "single_gain_supported_seasons": [
            season for season, row in by_season.items()
            if row["win_supported_by_one_gw"]
        ],
        "largest_single_gw_loss": float(np.min(all_values)),
        "largest_single_gw_gain": float(np.max(all_values)),
        "by_season": by_season,
    }


def paired_policy_bootstrap(baseline: pd.DataFrame, candidate: pd.DataFrame, *,
                            draws: int = 20_000, block_size: int = 4,
                            seed: int = 42) -> dict:
    """Simula temporadas pareadas remuestreando bloques contiguos de GWs.

    No inventa partidos: cuantifica incertidumbre de política con los deltas
    observados, conserva dependencia local mediante bloques y usa exactamente
    los mismos resultados para control y candidato.
    """
    merged = _paired_frame(baseline, candidate)
    seasons = {season: group.sort_values("gw")["delta"].to_numpy(dtype=float)
               for season, group in merged.groupby("season")}
    if not seasons:
        raise ValueError("no hay jornadas pareadas")

    observed = {str(season): float(values.sum()) for season, values in seasons.items()}
    target_len = int(round(np.median([len(values) for values in seasons.values()])))
    rng = np.random.default_rng(seed)
    names = list(seasons)
    simulations = np.empty(draws, dtype=float)
    for draw in range(draws):
        sampled = []
        while len(sampled) < target_len:
            values = seasons[names[int(rng.integers(0, len(names)))]]
            if len(values) <= block_size:
                block = values
            else:
                start = int(rng.integers(0, len(values) - block_size + 1))
                block = values[start:start + block_size]
            sampled.extend(block.tolist())
        simulations[draw] = sum(sampled[:target_len])

    return {
        "method": "paired_moving_block_bootstrap",
        "draws": int(draws),
        "block_size_gw": int(block_size),
        "observed_by_season": observed,
        "observed_mean": float(np.mean(list(observed.values()))),
        "simulated_mean": float(simulations.mean()),
        "ci90": [float(x) for x in np.quantile(simulations, [0.05, 0.95])],
        "ci95": [float(x) for x in np.quantile(simulations, [0.025, 0.975])],
        "probability_positive": float(np.mean(simulations > 0)),
        "downside_cvar_10": float(simulations[simulations <= np.quantile(simulations, 0.10)].mean()),
        "influence": paired_policy_influence(baseline, candidate),
    }
