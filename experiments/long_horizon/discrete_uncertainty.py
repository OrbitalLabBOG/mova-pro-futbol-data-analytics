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

from experiments.long_horizon.run import _git_sha, _sha256, _source_sha, _write_json
from mova_fpl.engine.discrete_uncertainty import (
    NFIX_WEIGHT,
    SUPPORT,
    UNIFORM_PSEUDOCOUNT,
    discrete_metrics,
    knn_discrete_pmf,
    normal_discrete_pmf,
)


EXPERIMENT_ID = "EXP-MOVA-2026-005"
PARENT_EXPERIMENT_ID = "EXP-MOVA-2026-003"
DEVELOPMENT_SEASONS = ("2021-22", "2023-24", "2024-25")
EXTERNAL_SEASON = "2025-26"
K_GRID = (50, 100, 200, 400)
PRIOR_STRENGTH_GRID = (0.0, 25.0, 100.0)
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
