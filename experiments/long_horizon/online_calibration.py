#!/usr/bin/env python3
"""Recalibración online causal del prior de clases de minutos.

Prueba si las clases 0 / 1-59 / 60+ cambian marginalmente al inicio de una
temporada. No reentrena el clasificador: ajusta sus probabilidades mediante la
razón entre el prior observado y el prior pronosticado, con shrinkage hacia el
modelo base. Toda etiqueta usada precede estrictamente a la GW objetivo.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from experiments.long_horizon.run import _git_sha, _sha256, _source_sha, _write_json
from experiments.long_horizon.season_boundary import predictive_metrics


EXPERIMENT_ID = "EXP-MOVA-2026-015"
PARENT_EXPERIMENT_ID = "EXP-MOVA-2026-013"
DEVELOPMENT_SEASONS = ("2021-22", "2023-24", "2024-25")
EXTERNAL_SEASON = "2025-26"
TARGET_GWS = tuple(range(3, 9))
STRENGTH_GWS = (0.5, 1.0, 2.0, 4.0)
DEFAULT_EXPERIMENTS = Path(__file__).resolve().parents[3] / "mova-fpl-experiments"
DEFAULT_PARENT = DEFAULT_EXPERIMENTS / PARENT_EXPERIMENT_ID
DEFAULT_OUTPUT = DEFAULT_EXPERIMENTS / EXPERIMENT_ID


def _file_spec(path: Path) -> dict:
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    return {
        "path": str(resolved), "bytes": resolved.stat().st_size,
        "sha256": _sha256(resolved),
    }


def freeze_manifest(args, output: Path) -> dict:
    root = Path(__file__).resolve().parents[2]
    parent = Path(args.parent_output).resolve()
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
        "inputs": {
            "development_predictions": _file_spec(
                parent / "development-predictions.csv.gz"
            ),
            "external_predictions": _file_spec(
                parent / "external-predictions.csv.gz"
            ),
            "canonical_db": _file_spec(Path(args.fpl_db)),
        },
        "development_seasons": list(DEVELOPMENT_SEASONS),
        "external_season": EXTERNAL_SEASON,
        "target_gws": list(TARGET_GWS),
        "base_variant": "append_full",
        "method": (
            "causal label-prior ratio adjustment with a Dirichlet-style prior "
            "centered on mean predicted class mass"
        ),
        "strength_grid_in_equivalent_gameweeks": list(STRENGTH_GWS),
        "managerial_pool": "top 20% value within season/GW/position, defined predeadline",
        "primary_metric": "three-class log loss",
        "selection_gate": (
            "candidate wins log loss in at least 2/3 development seasons, improves "
            "mean global log loss, and does not worsen managerial-pool log loss or p60 Brier"
        ),
        "external_gate": (
            "selected strength improves global and managerial-pool log loss plus p60 Brier"
        ),
        "promotion": "forbidden; diagnostic calibration layer only",
        "research_basis": [
            "Gneiting & Raftery (2007), strictly proper scoring rules",
            "Alexandari et al. (2020), maximum-likelihood label-shift adaptation",
            "Gibbs & Candes (2021), adaptive uncertainty under distribution shift",
        ],
    }
    destination = output / "manifest.json"
    if destination.exists():
        existing = json.loads(destination.read_text(encoding="utf-8"))
        strip_time = lambda value: {  # noqa: E731
            key: item for key, item in value.items() if key != "created_at"
        }
        if strip_time(existing) != strip_time(payload):
            raise RuntimeError(f"{EXPERIMENT_ID} ya existe bajo otros inputs")
        return existing
    _write_json(destination, payload)
    return payload


def prior_shift(probability: np.ndarray, calibration_probability: np.ndarray,
                calibration_y: np.ndarray, strength_gws: float,
                target_rows: int) -> tuple[np.ndarray, dict]:
    """Ajusta el prior de clase y conserva la razón condicional del modelo."""
    p = np.asarray(probability, dtype=float)
    calibration = np.asarray(calibration_probability, dtype=float)
    y = np.asarray(calibration_y, dtype=int)
    if p.ndim != 2 or p.shape[1] != 3 or calibration.shape[1] != 3:
        raise ValueError("se requieren probabilidades Nx3")
    if len(calibration) != len(y) or not len(y):
        raise ValueError("calibración vacía o desalineada")
    predicted_prior = np.clip(calibration.mean(axis=0), 1e-9, None)
    observed = np.bincount(y, minlength=3).astype(float)
    alpha = float(strength_gws) * float(target_rows)
    posterior_prior = (observed + alpha * predicted_prior) / (len(y) + alpha)
    ratio = posterior_prior / predicted_prior
    adjusted = p * ratio
    adjusted /= adjusted.sum(axis=1, keepdims=True)
    return adjusted, {
        "predicted_prior": predicted_prior.tolist(),
        "posterior_prior": posterior_prior.tolist(),
        "ratio": ratio.tolist(),
        "calibration_rows": int(len(y)),
        "prior_pseudocount": float(alpha),
    }


def _verify(spec: dict) -> Path:
    path = Path(spec["path"])
    if not path.is_file() or _sha256(path) != spec["sha256"]:
        raise RuntimeError(f"input ausente o alterado: {path}")
    return path


def _load_base(spec: dict, seasons: tuple[str, ...]) -> pd.DataFrame:
    frame = pd.read_csv(_verify(spec))
    frame = frame[
        frame["season"].isin(seasons) & frame["variant"].eq("append_full")
    ].copy()
    if frame.empty:
        raise RuntimeError(f"sin predicciones append_full para {seasons}")
    return frame


def _attach_managerial_pool(frame: pd.DataFrame, db_path: Path) -> pd.DataFrame:
    pairs = frame[["season", "gw"]].drop_duplicates()
    pieces = []
    with sqlite3.connect(db_path) as connection:
        for row in pairs.itertuples(index=False):
            prices = pd.read_sql_query(
                "SELECT element, MAX(value) AS value FROM player_gameweek "
                "WHERE season = ? AND gw = ? GROUP BY element",
                connection, params=(str(row.season), int(row.gw)),
            )
            prices["season"], prices["gw"] = str(row.season), int(row.gw)
            pieces.append(prices)
    prices = pd.concat(pieces, ignore_index=True)
    out = frame.merge(prices, on=["season", "gw", "element"], how="left")
    if out["value"].isna().any():
        raise RuntimeError("faltan precios predeadline para definir managerial_pool")
    threshold = out.groupby(["season", "gw", "position"])["value"].transform(
        lambda values: values.quantile(0.8)
    )
    out["managerial_pool"] = out["value"] >= threshold
    return out


def calibrated_rows(base: pd.DataFrame, strength_gws: float) -> pd.DataFrame:
    rows = []
    for season, season_frame in base.groupby("season", sort=True):
        for gw in TARGET_GWS:
            target = season_frame[season_frame["gw"] == gw].copy()
            calibration = season_frame[season_frame["gw"] < gw]
            if target.empty or calibration.empty:
                continue
            adjusted, _ = prior_shift(
                target[["p0", "p1", "p60"]].to_numpy(float),
                calibration[["p0", "p1", "p60"]].to_numpy(float),
                calibration["actual_class"].to_numpy(int),
                strength_gws,
                len(target),
            )
            target[["p0", "p1", "p60"]] = adjusted
            target["calibration"] = f"prior_shift_{strength_gws:g}gw"
            rows.append(target)
    return pd.concat(rows, ignore_index=True)


def _metrics(frame: pd.DataFrame) -> pd.DataFrame:
    records = []
    for (season, calibration), group in frame.groupby(
            ["season", "calibration"], sort=True):
        record = {
            "season": season,
            "calibration": calibration,
            **predictive_metrics(group),
        }
        pool = predictive_metrics(group[group["managerial_pool"]])
        record.update({f"managerial_{key}": value for key, value in pool.items()})
        records.append(record)
    return pd.DataFrame(records)


def _all_variants(base: pd.DataFrame) -> pd.DataFrame:
    untouched = base[base["gw"].isin(TARGET_GWS)].copy()
    untouched["calibration"] = "base"
    return pd.concat([
        untouched,
        *(calibrated_rows(base, strength) for strength in STRENGTH_GWS),
    ], ignore_index=True)


def select(args, output: Path, manifest: dict) -> dict:
    base = _load_base(
        manifest["inputs"]["development_predictions"], DEVELOPMENT_SEASONS,
    )
    base = _attach_managerial_pool(
        base, _verify(manifest["inputs"]["canonical_db"]),
    )
    metrics = _metrics(_all_variants(base))
    means = metrics.groupby("calibration").mean(numeric_only=True)
    pivot = metrics.pivot(
        index="season", columns="calibration", values="log_loss_3c",
    )
    eligible = []
    for calibration in means.index:
        if calibration == "base":
            continue
        wins = int((pivot[calibration] < pivot["base"]).sum())
        if (wins >= 2
                and means.loc[calibration, "log_loss_3c"] < means.loc["base", "log_loss_3c"]
                and means.loc[calibration, "managerial_log_loss_3c"]
                <= means.loc["base", "managerial_log_loss_3c"]
                and means.loc[calibration, "brier_p60"] <= means.loc["base", "brier_p60"]):
            eligible.append(calibration)
    selected = min(
        eligible, key=lambda name: means.loc[name, "log_loss_3c"],
    ) if eligible else "base"
    payload = {
        "experiment_id": manifest["experiment_id"],
        "source_sha256": manifest["source_sha256"],
        "selected_calibration": selected,
        "candidate_accepted": selected != "base",
        "eligible": eligible,
        "mean_metrics": {
            str(index): {str(key): float(value) for key, value in row.items()}
            for index, row in means.iterrows()
        },
        "season_metrics": metrics.to_dict("records"),
        "promotion": "not_authorized",
    }
    metrics.to_csv(output / "development-metrics.csv", index=False)
    _write_json(output / "selection.json", payload)
    return payload


def external(args, output: Path, manifest: dict) -> dict:
    destination = output / "external-evaluation.json"
    selection_path = output / "selection.json"
    if not selection_path.exists():
        raise FileNotFoundError("falta selection.json")
    selection = json.loads(selection_path.read_text())
    selected = str(selection["selected_calibration"])
    if selected == "base":
        raise RuntimeError("ninguna recalibración online pasó desarrollo")
    if destination.exists():
        existing = json.loads(destination.read_text())
        if (existing.get("source_sha256") == manifest["source_sha256"]
                and existing.get("selected_calibration") == selected):
            return existing
        raise RuntimeError("externo ya abierto bajo otra selección")
    strength = float(selected.removeprefix("prior_shift_").removesuffix("gw"))
    base = _load_base(manifest["inputs"]["external_predictions"], (EXTERNAL_SEASON,))
    base = _attach_managerial_pool(
        base, _verify(manifest["inputs"]["canonical_db"]),
    )
    untouched = base[base["gw"].isin(TARGET_GWS)].copy()
    untouched["calibration"] = "base"
    rows = pd.concat([untouched, calibrated_rows(base, strength)], ignore_index=True)
    metrics = _metrics(rows).set_index("calibration")
    deltas = {
        key: float(metrics.loc[selected, key] - metrics.loc["base", key])
        for key in ("log_loss_3c", "managerial_log_loss_3c", "brier_p60")
    }
    accepted = all(value < 0 for value in deltas.values())
    payload = {
        "experiment_id": manifest["experiment_id"],
        "source_sha256": manifest["source_sha256"],
        "external_opened_once": True,
        "selected_calibration": selected,
        "metrics": metrics.reset_index().to_dict("records"),
        "deltas_vs_base": deltas,
        "candidate_accepted": bool(accepted),
        "promotion": "not_authorized",
    }
    _write_json(destination, payload)
    return payload


def parse_args():
    main_repo = Path(__file__).resolve().parents[3] / "mova-pro-futbol-data-analytics"
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("manifest", "select", "external"))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--parent-output", default=str(DEFAULT_PARENT))
    parser.add_argument(
        "--fpl-db", default=str(main_repo / "data/processed/fpl_canonical.db"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest = freeze_manifest(args, output)
    if args.phase == "manifest":
        result = manifest
    elif args.phase == "select":
        result = select(args, output, manifest)
    else:
        result = external(args, output, manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
