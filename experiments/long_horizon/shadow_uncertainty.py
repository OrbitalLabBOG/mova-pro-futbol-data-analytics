#!/usr/bin/env python3
"""Empaqueta el calibrador discreto aprobado para un shadow 2026-27."""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from experiments.long_horizon.run import _git_sha, _sha256, _source_sha, _write_json
from mova_fpl.engine.discrete_uncertainty import write_calibration_artifact


EXPERIMENT_ID = "EXP-MOVA-2026-006"
PARENT_EXPERIMENT_ID = "EXP-MOVA-2026-005"
DEFAULT_EXPERIMENTS = Path(__file__).resolve().parents[3] / "mova-fpl-experiments"
DEFAULT_PARENT = DEFAULT_EXPERIMENTS / PARENT_EXPERIMENT_ID
DEFAULT_OUTPUT = DEFAULT_EXPERIMENTS / EXPERIMENT_ID


def _read_json(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def freeze_manifest(parent: Path, output: Path) -> dict:
    root = Path(__file__).resolve().parents[2]
    parent_manifest_path = parent / "manifest.json"
    selection_path = parent / "selection.json"
    evaluation_path = parent / "external-evaluation.json"
    parent_manifest = _read_json(parent_manifest_path)
    selection = _read_json(selection_path)
    evaluation = _read_json(evaluation_path)
    selected = selection.get("selected") or {}
    if (parent_manifest.get("experiment_id") != PARENT_EXPERIMENT_ID
            or not selected.get("accepted")
            or selected.get("method") != "knn_empirical_discrete"):
        raise RuntimeError("el experimento padre no aprobó un calibrador discreto")
    if evaluation.get("promotion") != "not_authorized":
        raise RuntimeError("estado de promoción inesperado en evaluación padre")
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
        "parent_artifacts": {
            "manifest": {"path": str(parent_manifest_path),
                         "sha256": _sha256(parent_manifest_path)},
            "selection": {"path": str(selection_path), "sha256": _sha256(selection_path)},
            "external_evaluation": {"path": str(evaluation_path),
                                    "sha256": _sha256(evaluation_path)},
        },
        "inputs": parent_manifest["inputs"],
        "fitted_seasons": list(parent_manifest["development_seasons"])
                          + [parent_manifest["external_evaluation_season"]],
        "neighbors": int(selected["neighbors"]),
        "prior_strength": float(selected["prior_strength"]),
        "target_season": "2026-27",
        "role": "optional non-executable strategy-shadow uncertainty diagnostics",
        "policy_mean_changed": False,
        "production_traffic_percent": 0,
        "promotion": "forbidden; explicit approval required",
    }
    destination = output / "manifest.json"
    if destination.exists():
        existing = _read_json(destination)
        old = {key: value for key, value in existing.items() if key != "created_at"}
        serialized = json.loads(json.dumps(payload, ensure_ascii=False, default=str))
        new = {key: value for key, value in serialized.items() if key != "created_at"}
        if old != new:
            raise RuntimeError("EXP-MOVA-2026-006 ya existe bajo otro código o inputs")
        return existing
    _write_json(destination, payload)
    return payload


def build(manifest: dict, output: Path) -> dict:
    frames = []
    for season in manifest["fitted_seasons"]:
        spec = manifest["inputs"][season]
        path = Path(spec["path"])
        if _sha256(path) != spec["sha256"]:
            raise RuntimeError(f"input modificado para {season}")
        frame = pd.read_csv(path)
        frame["calibration_season"] = season
        frames.append(frame)
    calibration = pd.concat(frames, ignore_index=True)
    descriptor = write_calibration_artifact(
        output / "live-calibrator.npz",
        calibration,
        metadata={
            "experiment_id": manifest["experiment_id"],
            "parent_experiment_id": manifest["parent_experiment_id"],
            "source_sha256": manifest["source_sha256"],
            "fitted_seasons": manifest["fitted_seasons"],
            "neighbors": manifest["neighbors"],
            "prior_strength": manifest["prior_strength"],
            "target_season": manifest["target_season"],
            "policy_mean_changed": False,
            "selected_for_execution": False,
        },
    )
    payload = {
        "experiment_id": manifest["experiment_id"],
        "source_sha256": manifest["source_sha256"],
        "status": "shadow_ready",
        "artifact": descriptor,
        "rows_by_season": {
            str(key): int(value)
            for key, value in calibration.groupby("calibration_season").size().items()
        },
        "rows": int(len(calibration)),
        "selected_for_execution": False,
        "policy_mean_changed": False,
        "promotion": "not_authorized",
    }
    _write_json(output / "artifact.json", payload)
    return payload


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent", default=str(DEFAULT_PARENT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    parent = Path(args.parent).resolve()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    result = build(freeze_manifest(parent, output), output)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
