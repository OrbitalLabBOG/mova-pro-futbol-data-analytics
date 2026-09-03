#!/usr/bin/env python3
"""Calibracion temporal de una distribucion discreta de puntos FPL.

El modelo de componentes ya produce una media y una desviacion, pero la Normal
resultante no puede representar el gran atomo en cero ni el soporte entero con
pocos valores negativos. Este experimento aprende una distribucion empirica
condicionada por posicion, xP, desviacion y numero de fixtures usando solamente
predicciones y resultados de temporadas anteriores.

La distribucion es diagnostica: no cambia xP, transferencias ni capitan. Su
promocion al runtime queda prohibida hasta demostrar calibracion externa y
comportamiento vivo.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import ndtr
from sklearn.neighbors import NearestNeighbors

from experiments.long_horizon.run import _git_sha, _sha256, _source_sha, _write_json


EXPERIMENT_ID = "EXP-MOVA-2026-005"
PARENT_EXPERIMENT_ID = "EXP-MOVA-2026-003"
SUPPORT = np.arange(-6, 37, dtype=int)
DEVELOPMENT_SEASONS = ("2021-22", "2023-24", "2024-25")
EXTERNAL_SEASON = "2025-26"
K_GRID = (50, 100, 200, 400)
PRIOR_STRENGTH_GRID = (0.0, 25.0, 100.0)
UNIFORM_PSEUDOCOUNT = 0.01
NFIX_WEIGHT = 2.0
DEFAULT_EXPERIMENTS = Path(__file__).resolve().parents[3] / "mova-fpl-experiments"
DEFAULT_DEVELOPMENT_ROOT = DEFAULT_EXPERIMENTS / "EXP-MOVA-2026-004"
DEFAULT_EXTERNAL_ROOT = DEFAULT_EXPERIMENTS / PARENT_EXPERIMENT_ID
DEFAULT_OUTPUT = DEFAULT_EXPERIMENTS / EXPERIMENT_ID


def _prediction_path(root: Path, season: str) -> Path:
    return root / "replays" / f"{season}-season_fixture_h3-predictions.csv.gz"


def _input_spec(args) -> dict:
    development_root = Path(args.development_root).resolve()
    external_root = Path(args.external_root).resolve()
    paths = {
        season: _prediction_path(development_root, season)
        for season in DEVELOPMENT_SEASONS
    }
    paths[EXTERNAL_SEASON] = _prediction_path(external_root, EXTERNAL_SEASON)
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"faltan predicciones parentales: {missing}")
    return {
        season: {"path": str(path), "bytes": path.stat().st_size,
                 "sha256": _sha256(path)}
        for season, path in paths.items()
    }


def freeze_manifest(args, output: Path) -> dict:
    root = Path(__file__).resolve().parents[2]
    payload = {
        "experiment_id": EXPERIMENT_ID,
        "parent_experiment_id": PARENT_EXPERIMENT_ID,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_sha": _git_sha(root),
        "source_sha256": _source_sha(root),
        "branch": subprocess.run(
            ["git", "branch", "--show-current"], cwd=root, check=True,
            capture_output=True, text=True,
        ).stdout.strip(),
        "inputs": _input_spec(args),
        "development_seasons": DEVELOPMENT_SEASONS,
        "external_evaluation_season": EXTERNAL_SEASON,
        "support": SUPPORT.tolist(),
        "method": "position-stratified k-nearest-neighbor empirical PMF",
        "features": ["xp", "xp_sd", f"n_fixtures*{NFIX_WEIGHT:g}"],
        "k_grid": K_GRID,
        "position_prior_strength_grid": PRIOR_STRENGTH_GRID,
        "uniform_pseudocount_per_support_value": UNIFORM_PSEUDOCOUNT,
        "selection_folds": [
            {"calibration": ["2021-22"], "target": "2023-24"},
            {"calibration": ["2021-22", "2023-24"], "target": "2024-25"},
        ],
        "selection_rule": (
            "minimum mean discrete CRPS; candidate must beat discretized Normal "
            "in both temporal development folds"
        ),
        "role": "uncertainty calibration only; expected-points policy remains unchanged",
        "promotion": "forbidden; requires external evaluation and live shadow",
        "known_limitations": [
            "2025-26 was visible in the parent policy analysis and is not a cognitively "
            "pristine holdout",
            "nearest-neighbor PMFs inherit historical support and regime mix",
            "fixture-count is modeled, but shared availability correlation in DGW is not",
        ],
    }
    destination = output / "manifest.json"
    if destination.exists():
        existing = json.loads(destination.read_text(encoding="utf-8"))
        old = {key: value for key, value in existing.items() if key != "created_at"}
        serialized = json.loads(json.dumps(payload, ensure_ascii=False, default=str))
        new = {key: value for key, value in serialized.items() if key != "created_at"}
        if old != new:
            raise RuntimeError(
                "el manifest EXP-MOVA-2026-005 ya existe bajo otro codigo o inputs"
            )
        return existing
    _write_json(destination, payload)
    return payload


def _verify_and_load(manifest: dict, season: str) -> pd.DataFrame:
    spec = manifest["inputs"][season]
    path = Path(spec["path"])
    if _sha256(path) != spec["sha256"]:
        raise RuntimeError(f"hash de predicciones no coincide para {season}")
    frame = pd.read_csv(path)
    required = {"element", "position", "xp", "xp_sd", "n_fixtures", "actual", "gw"}
    if not required <= set(frame):
        raise ValueError(f"predicciones {season} sin columnas {sorted(required - set(frame))}")
    actual = pd.to_numeric(frame["actual"], errors="raise").to_numpy(dtype=float)
    if not np.all(actual == np.rint(actual)):
        raise ValueError(f"resultados no enteros en {season}")
    if actual.min() < SUPPORT[0] or actual.max() > SUPPORT[-1]:
        raise ValueError(f"resultado fuera del soporte congelado en {season}")
    return frame


def normal_discrete_pmf(mean, sd, support: np.ndarray = SUPPORT) -> np.ndarray:
    """Discretiza una Normal en intervalos unitarios y conserva sus dos colas."""
    mu = np.asarray(mean, dtype=float)
    sigma = np.asarray(sd, dtype=float)
    if mu.shape != sigma.shape:
        raise ValueError("mean y sd deben tener la misma forma")
    if not np.isfinite(mu).all():
        raise ValueError("mean debe ser finita")
    out = np.zeros((len(mu), len(support)), dtype=float)
    valid = np.isfinite(sigma) & (sigma > 1e-9)
    if valid.any():
        z_hi = ((support[None, :] + 0.5) - mu[valid, None]) / sigma[valid, None]
        z_lo = ((support[None, :] - 0.5) - mu[valid, None]) / sigma[valid, None]
        rows = ndtr(z_hi) - ndtr(z_lo)
        rows[:, 0] = ndtr((support[0] + 0.5 - mu[valid]) / sigma[valid])
        rows[:, -1] = 1.0 - ndtr(
            (support[-1] - 0.5 - mu[valid]) / sigma[valid]
        )
        out[valid] = rows
    invalid = ~valid
    if invalid.any():
        nearest = np.abs(support[None, :] - mu[invalid, None]).argmin(axis=1)
        out[np.flatnonzero(invalid), nearest] = 1.0
    sums = out.sum(axis=1, keepdims=True)
    return out / np.where(sums > 0, sums, 1.0)


def knn_discrete_pmf(calibration: pd.DataFrame, target: pd.DataFrame, *,
                     neighbors: int, prior_strength: float,
                     support: np.ndarray = SUPPORT) -> np.ndarray:
    """PMF empírica causal, estratificada por posición y suavizada."""
    if neighbors <= 0 or prior_strength < 0:
        raise ValueError("neighbors y prior_strength inválidos")
    out = np.zeros((len(target), len(support)), dtype=float)
    positions = target["position"].fillna("UNKNOWN").astype(str)
    calibration_positions = calibration["position"].fillna("UNKNOWN").astype(str)
    for position in sorted(positions.unique()):
        target_mask = (positions == position).to_numpy()
        calibration_mask = (calibration_positions == position).to_numpy()
        if not calibration_mask.any():
            calibration_mask = np.ones(len(calibration), dtype=bool)
        past = calibration.loc[calibration_mask]
        future = target.loc[target_mask]

        center = past[["xp", "xp_sd"]].mean().to_numpy(dtype=float)
        scale = past[["xp", "xp_sd"]].std().to_numpy(dtype=float)
        scale = np.where(np.isfinite(scale) & (scale > 1e-9), scale, 1.0)
        past_x = (past[["xp", "xp_sd"]].to_numpy(dtype=float) - center) / scale
        future_x = (future[["xp", "xp_sd"]].to_numpy(dtype=float) - center) / scale
        past_x = np.column_stack([
            past_x,
            pd.to_numeric(past["n_fixtures"], errors="coerce").fillna(1.0)
            .to_numpy(dtype=float) * NFIX_WEIGHT,
        ])
        future_x = np.column_stack([
            future_x,
            pd.to_numeric(future["n_fixtures"], errors="coerce").fillna(1.0)
            .to_numpy(dtype=float) * NFIX_WEIGHT,
        ])
        k = min(int(neighbors), len(past))
        indices = NearestNeighbors(n_neighbors=k).fit(past_x).kneighbors(
            future_x, return_distance=False
        )
        actual_indices = (
            pd.to_numeric(past["actual"], errors="raise").to_numpy(dtype=int)
            - int(support[0])
        )
        if actual_indices.min() < 0 or actual_indices.max() >= len(support):
            raise ValueError("calibration contiene resultados fuera del soporte")
        counts = np.full(
            (len(future), len(support)), UNIFORM_PSEUDOCOUNT, dtype=float
        )
        np.add.at(
            counts,
            (np.arange(len(future))[:, None], actual_indices[indices]),
            1.0,
        )
        prior = np.bincount(actual_indices, minlength=len(support)).astype(float)
        prior += UNIFORM_PSEUDOCOUNT
        prior /= prior.sum()
        counts += float(prior_strength) * prior
        out[target_mask] = counts / counts.sum(axis=1, keepdims=True)
    if not np.allclose(out.sum(axis=1), 1.0):
        raise RuntimeError("PMF no normalizada")
    return out


def discrete_metrics(actual, pmf: np.ndarray,
                     support: np.ndarray = SUPPORT) -> dict:
    """Proper scores, calibración y sharpness para una PMF de puntos enteros."""
    y = np.asarray(actual, dtype=int)
    probabilities = np.asarray(pmf, dtype=float)
    if probabilities.shape != (len(y), len(support)):
        raise ValueError("dimensiones incompatibles entre actual y PMF")
    if (probabilities < 0).any() or not np.allclose(probabilities.sum(axis=1), 1.0):
        raise ValueError("PMF inválida")
    if y.min() < support[0] or y.max() > support[-1]:
        raise ValueError("actual fuera del soporte")
    cdf = np.cumsum(probabilities, axis=1)
    observed_cdf = support[None, :] >= y[:, None]
    crps = np.sum((cdf - observed_cdf) ** 2, axis=1)
    indices = y - int(support[0])
    row = np.arange(len(y))
    mean = probabilities @ support.astype(float)
    variance = probabilities @ (support.astype(float) ** 2) - mean ** 2
    result = {
        "rows": int(len(y)),
        "crps_discrete": float(crps.mean()),
        "log_score": float(-np.log(np.clip(probabilities[row, indices], 1e-15, 1.0)).mean()),
        "mean_mae": float(np.abs(mean - y).mean()),
        "mean_rmse": float(np.sqrt(np.mean((mean - y) ** 2))),
        "mean_bias": float(np.mean(mean - y)),
        "predictive_sd_mean": float(np.sqrt(np.clip(variance, 0.0, None)).mean()),
    }
    zero_index = int(np.flatnonzero(support == 0)[0])
    p_zero = probabilities[:, zero_index]
    y_zero = (y == 0).astype(float)
    result |= {
        "zero_brier": float(np.mean((p_zero - y_zero) ** 2)),
        "predicted_zero_rate": float(p_zero.mean()),
        "observed_zero_rate": float(y_zero.mean()),
    }
    for label, level in (("50", 0.50), ("80", 0.80), ("90", 0.90)):
        lower_q = (1.0 - level) / 2.0
        upper_q = 1.0 - lower_q
        lower = support[np.argmax(cdf >= lower_q, axis=1)]
        upper = support[np.argmax(cdf >= upper_q, axis=1)]
        result[f"coverage_{label}"] = float(np.mean((y >= lower) & (y <= upper)))
        result[f"interval_width_{label}"] = float(np.mean(upper - lower))
    return result


def select_calibrator(manifest: dict, output: Path) -> dict:
    frames = {season: _verify_and_load(manifest, season)
              for season in DEVELOPMENT_SEASONS}
    rows = []
    folds = manifest["selection_folds"]
    for fold in folds:
        calibration = pd.concat(
            [frames[season] for season in fold["calibration"]], ignore_index=True
        )
        target = frames[fold["target"]]
        normal = discrete_metrics(
            target["actual"].to_numpy(dtype=int),
            normal_discrete_pmf(target["xp"], target["xp_sd"]),
        )
        for neighbors in K_GRID:
            for prior_strength in PRIOR_STRENGTH_GRID:
                candidate = discrete_metrics(
                    target["actual"].to_numpy(dtype=int),
                    knn_discrete_pmf(
                        calibration, target, neighbors=neighbors,
                        prior_strength=prior_strength,
                    ),
                )
                rows.append({
                    "target_season": fold["target"],
                    "calibration_seasons": ",".join(fold["calibration"]),
                    "neighbors": int(neighbors),
                    "prior_strength": float(prior_strength),
                    **{f"candidate_{key}": value for key, value in candidate.items()},
                    **{f"normal_{key}": value for key, value in normal.items()},
                    "crps_delta_vs_normal": (
                        candidate["crps_discrete"] - normal["crps_discrete"]
                    ),
                })
    metrics = pd.DataFrame(rows)
    aggregate = (metrics.groupby(["neighbors", "prior_strength"], as_index=False)
                 .agg(mean_crps=("candidate_crps_discrete", "mean"),
                      mean_delta_vs_normal=("crps_delta_vs_normal", "mean"),
                      wins_vs_normal=("crps_delta_vs_normal", lambda values: int((values < 0).sum())),
                      mean_zero_brier=("candidate_zero_brier", "mean"),
                      mean_log_score=("candidate_log_score", "mean")))
    eligible = aggregate[aggregate["wins_vs_normal"] == len(folds)].copy()
    if eligible.empty:
        selected = {"method": "discretized_normal", "accepted": False}
    else:
        best = eligible.sort_values(
            ["mean_crps", "neighbors", "prior_strength"], kind="stable"
        ).iloc[0]
        selected = {
            "method": "knn_empirical_discrete",
            "accepted": True,
            "neighbors": int(best["neighbors"]),
            "prior_strength": float(best["prior_strength"]),
            "mean_crps": float(best["mean_crps"]),
            "mean_delta_vs_normal": float(best["mean_delta_vs_normal"]),
            "wins_vs_normal": int(best["wins_vs_normal"]),
        }
    payload = {
        "experiment_id": manifest["experiment_id"],
        "source_sha256": manifest["source_sha256"],
        "input_sha256": {
            season: manifest["inputs"][season]["sha256"]
            for season in DEVELOPMENT_SEASONS
        },
        "selection_only": True,
        "selected": selected,
        "selection_rule": manifest["selection_rule"],
        "aggregate": aggregate.to_dict("records"),
        "promotion": "not_authorized",
    }
    _write_json(output / "selection.json", payload)
    metrics.to_csv(output / "selection-fold-metrics.csv", index=False)
    aggregate.to_csv(output / "selection-aggregate.csv", index=False)
    return payload


def external_evaluation(manifest: dict, output: Path) -> dict:
    selection_path = output / "selection.json"
    if not selection_path.exists():
        raise FileNotFoundError("falta selection.json; ejecute select primero")
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    if selection.get("source_sha256") != manifest["source_sha256"]:
        raise RuntimeError("la seleccion no pertenece al manifest vigente")
    selected = selection.get("selected") or {}
    if not selected.get("accepted"):
        raise RuntimeError("ningun calibrador discreto supero el gate de desarrollo")
    destination = output / "external-evaluation.json"
    if destination.exists():
        sealed = json.loads(destination.read_text(encoding="utf-8"))
        if (sealed.get("source_sha256") == manifest["source_sha256"]
                and sealed.get("input_sha256") == manifest["inputs"][EXTERNAL_SEASON]["sha256"]):
            return sealed
        raise RuntimeError("evaluacion externa ya abierta bajo otro codigo o input")

    calibration = pd.concat(
        [_verify_and_load(manifest, season) for season in DEVELOPMENT_SEASONS],
        ignore_index=True,
    )
    target = _verify_and_load(manifest, EXTERNAL_SEASON)
    candidate_pmf = knn_discrete_pmf(
        calibration, target,
        neighbors=int(selected["neighbors"]),
        prior_strength=float(selected["prior_strength"]),
    )
    normal_pmf = normal_discrete_pmf(target["xp"], target["xp_sd"])
    actual = target["actual"].to_numpy(dtype=int)
    artifact = output / "external-pmf.npz"
    temporary = artifact.with_suffix(".npz.tmp")
    with temporary.open("wb") as handle:
        np.savez_compressed(
            handle,
            support=SUPPORT,
            pmf=candidate_pmf.astype(np.float32),
            actual=actual.astype(np.int16),
            gw=target["gw"].to_numpy(dtype=np.int16),
            element=target["element"].to_numpy(dtype=np.int32),
        )
    temporary.replace(artifact)
    payload = {
        "experiment_id": manifest["experiment_id"],
        "source_sha256": manifest["source_sha256"],
        "input_sha256": manifest["inputs"][EXTERNAL_SEASON]["sha256"],
        "season": EXTERNAL_SEASON,
        "selected": selected,
        "candidate_metrics": discrete_metrics(actual, candidate_pmf),
        "discretized_normal_metrics": discrete_metrics(actual, normal_pmf),
        "pmf_artifact": {
            "path": str(artifact), "bytes": artifact.stat().st_size,
            "sha256": _sha256(artifact),
        },
        "policy_changed": False,
        "promotion": "not_authorized",
    }
    payload["crps_delta_vs_normal"] = (
        payload["candidate_metrics"]["crps_discrete"]
        - payload["discretized_normal_metrics"]["crps_discrete"]
    )
    _write_json(destination, payload)
    return payload


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("manifest", "select", "external-evaluation"))
    parser.add_argument("--development-root", default=str(DEFAULT_DEVELOPMENT_ROOT))
    parser.add_argument("--external-root", default=str(DEFAULT_EXTERNAL_ROOT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest = freeze_manifest(args, output)
    if args.phase == "manifest":
        result = manifest
    elif args.phase == "select":
        result = select_calibrator(manifest, output)
    else:
        result = external_evaluation(manifest, output)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
