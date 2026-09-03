"""Distribuciones discretas de puntos para diagnóstico probabilístico."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import ndtr
from sklearn.neighbors import NearestNeighbors


ARTIFACT_SCHEMA = "mova-discrete-calibrator-v1"
SHADOW_SCHEMA = "mova-discrete-shadow-v1"
SUPPORT = np.arange(-6, 37, dtype=int)
UNIFORM_PSEUDOCOUNT = 0.01
NFIX_WEIGHT = 2.0
REQUIRED_COLUMNS = {"position", "xp", "xp_sd", "n_fixtures"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    required_calibration = REQUIRED_COLUMNS | {"actual"}
    if not required_calibration <= set(calibration):
        raise ValueError("calibration incompleta")
    if not REQUIRED_COLUMNS <= set(target):
        raise ValueError("target incompleto")
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


def write_calibration_artifact(path: Path, calibration: pd.DataFrame, *,
                               metadata: dict) -> dict:
    """Escribe arrays tipados sin pickle y devuelve descriptor con SHA-256."""
    required = REQUIRED_COLUMNS | {"actual"}
    if not required <= set(calibration):
        raise ValueError(f"calibration incompleta: {sorted(required - set(calibration))}")
    frame = calibration.reset_index(drop=True)
    body = {
        **metadata,
        "schema": ARTIFACT_SCHEMA,
        "rows": int(len(frame)),
        "support": SUPPORT.tolist(),
    }
    metadata_bytes = np.frombuffer(
        json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8"),
        dtype=np.uint8,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as handle:
        np.savez_compressed(
            handle,
            metadata_json=metadata_bytes,
            position=frame["position"].fillna("UNKNOWN").astype(str).to_numpy(dtype="U16"),
            xp=frame["xp"].to_numpy(dtype=np.float32),
            xp_sd=frame["xp_sd"].to_numpy(dtype=np.float32),
            n_fixtures=frame["n_fixtures"].to_numpy(dtype=np.int8),
            actual=frame["actual"].to_numpy(dtype=np.int16),
        )
    temporary.replace(path)
    return {"path": str(path), "bytes": path.stat().st_size,
            "sha256": sha256_file(path), "metadata": body}


def load_calibration_artifact(path: Path, expected_sha256: str) -> tuple[pd.DataFrame, dict]:
    """Verifica hash/schema y carga un NPZ con ``allow_pickle=False``."""
    if len(str(expected_sha256)) != 64 or sha256_file(path) != expected_sha256:
        raise ValueError("SHA-256 del calibrador discreto no coincide")
    with np.load(path, allow_pickle=False) as bundle:
        required = {"metadata_json", "position", "xp", "xp_sd", "n_fixtures", "actual"}
        if not required <= set(bundle.files):
            raise ValueError("artefacto discreto incompleto")
        metadata = json.loads(bundle["metadata_json"].astype(np.uint8).tobytes())
        frame = pd.DataFrame({
            "position": bundle["position"].astype(str),
            "xp": bundle["xp"].astype(float),
            "xp_sd": bundle["xp_sd"].astype(float),
            "n_fixtures": bundle["n_fixtures"].astype(int),
            "actual": bundle["actual"].astype(int),
        })
    if metadata.get("schema") != ARTIFACT_SCHEMA:
        raise ValueError("schema del calibrador discreto incompatible")
    if metadata.get("support") != SUPPORT.tolist() or int(metadata.get("rows", 0)) != len(frame):
        raise ValueError("metadata del calibrador discreto no coincide")
    return frame, metadata


def shadow_distribution(target: pd.DataFrame, *, artifact_path: Path,
                        artifact_sha256: str, neighbors: int = 200,
                        prior_strength: float = 0.0) -> dict:
    """Genera PMFs auditables para la jornada actual, sin tocar la media de política."""
    if "element" not in target:
        raise ValueError("target discreto sin element")
    calibration, metadata = load_calibration_artifact(
        artifact_path, artifact_sha256
    )
    probabilities = knn_discrete_pmf(
        calibration, target, neighbors=neighbors, prior_strength=prior_strength
    )
    support = SUPPORT.astype(float)
    cdf = np.cumsum(probabilities, axis=1)
    means = probabilities @ support
    variances = probabilities @ (support ** 2) - means ** 2
    zero_index = int(np.flatnonzero(SUPPORT == 0)[0])
    rows = {}
    for index, element in enumerate(target["element"].to_numpy(dtype=int)):
        rows[str(element)] = {
            "optimization_xp": float(target.iloc[index]["xp"]),
            "pmf_mean": float(means[index]),
            "pmf_sd": float(np.sqrt(max(0.0, variances[index]))),
            "p_zero": float(probabilities[index, zero_index]),
            "q10": int(SUPPORT[np.argmax(cdf[index] >= 0.10)]),
            "q50": int(SUPPORT[np.argmax(cdf[index] >= 0.50)]),
            "q90": int(SUPPORT[np.argmax(cdf[index] >= 0.90)]),
            "pmf": probabilities[index].tolist(),
        }
    return {
        "schema": SHADOW_SCHEMA,
        "experiment_id": metadata.get("experiment_id"),
        "artifact_sha256": artifact_sha256,
        "support": SUPPORT.tolist(),
        "neighbors": int(neighbors),
        "prior_strength": float(prior_strength),
        "rows": rows,
        "row_count": len(rows),
        "optimization_mean_unchanged": True,
        "selected_for_execution": False,
    }
