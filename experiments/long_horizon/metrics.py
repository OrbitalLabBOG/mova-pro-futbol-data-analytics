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


def paired_policy_bootstrap(baseline: pd.DataFrame, candidate: pd.DataFrame, *,
                            draws: int = 20_000, block_size: int = 4,
                            seed: int = 42) -> dict:
    """Simula temporadas pareadas remuestreando bloques contiguos de GWs.

    No inventa partidos: cuantifica incertidumbre de política con los deltas
    observados, conserva dependencia local mediante bloques y usa exactamente
    los mismos resultados para control y candidato.
    """
    keys = ["season", "gw"]
    merged = baseline[keys + ["points"]].merge(
        candidate[keys + ["points"]], on=keys, suffixes=("_baseline", "_candidate"),
        validate="one_to_one",
    )
    merged["delta"] = merged["points_candidate"] - merged["points_baseline"]
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
    }
