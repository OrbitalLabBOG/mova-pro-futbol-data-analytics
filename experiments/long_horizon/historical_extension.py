#!/usr/bin/env python3
"""Extensión post hoc de la política h3 a la temporada 2020/21.

Este experimento no reabre la selección de hiperparámetros. Añade una quinta
temporada completa, valida primero que el motor reproduce exactamente sus
puntos jugador-partido y luego contrasta las dos políticas ya congeladas.
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

from experiments.long_horizon.metrics import paired_policy_bootstrap
from experiments.long_horizon.run import (
    CachedStore,
    INHERITED_EVENT_WEIGHT,
    POLICY_VARIANTS,
    _git_sha,
    _model_source_sha,
    _sha256,
    _source_sha,
    _write_json,
    run_variant,
)
from mova_fpl.rules import PlayerStats, Position, score


EXPERIMENT_ID = "EXP-MOVA-2026-007"
PARENT_EXPERIMENT_ID = "EXP-MOVA-2026-003"
TARGET_SEASON = "2020-21"
PARENT_SEASONS = ("2021-22", "2023-24", "2024-25", "2025-26")
VARIANTS = ("control_h3", "season_fixture_h3")
DEFAULT_EXPERIMENT_ROOT = (
    Path(__file__).resolve().parents[3] / "mova-fpl-experiments"
)
DEFAULT_OUTPUT = DEFAULT_EXPERIMENT_ROOT / EXPERIMENT_ID
DEFAULT_PARENT_OUTPUT = DEFAULT_EXPERIMENT_ROOT / PARENT_EXPERIMENT_ID


def _parent_files(parent: Path) -> list[Path]:
    files = [parent / "manifest.json"]
    files.extend(
        parent / "replays" / f"{season}-{variant}.json"
        for season in PARENT_SEASONS
        for variant in VARIANTS
    )
    missing = [str(path) for path in files if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"faltan artefactos padre: {missing}")
    return files


def freeze_manifest(args, output: Path) -> dict:
    root = Path(__file__).resolve().parents[2]
    db = Path(args.fpl_db).resolve()
    parent = Path(args.parent_output).resolve()
    parent_files = _parent_files(parent)
    parent_manifest = json.loads(parent_files[0].read_text(encoding="utf-8"))
    dataset_sha = _sha256(db)
    if parent_manifest.get("experiment_id") != PARENT_EXPERIMENT_ID:
        raise RuntimeError("el directorio padre no corresponde a EXP-MOVA-2026-003")
    if parent_manifest.get("dataset", {}).get("sha256") != dataset_sha:
        raise RuntimeError("el dataset vigente no coincide con la evidencia padre")

    payload = {
        "experiment_id": EXPERIMENT_ID,
        "parent_experiment_id": PARENT_EXPERIMENT_ID,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_sha": _git_sha(root),
        "source_sha256": _source_sha(root),
        "model_source_sha256": _model_source_sha(root),
        "branch": subprocess.run(
            ["git", "branch", "--show-current"], cwd=root, check=True,
            capture_output=True, text=True,
        ).stdout.strip(),
        "dataset": {
            "path": str(db), "bytes": db.stat().st_size, "sha256": dataset_sha,
        },
        "parent_evidence": {
            "path": str(parent),
            "files": {
                str(path.relative_to(parent)): _sha256(path) for path in parent_files
            },
        },
        "target_season": TARGET_SEASON,
        "historical_context_seasons": list(PARENT_SEASONS),
        "variants": {name: POLICY_VARIANTS[name] for name in VARIANTS},
        "north_star": "PVA-38 paired season points vs control_h3",
        "classification": "posthoc historical robustness extension; not model selection",
        "promotion": "forbidden; live causal shadow and explicit approval still required",
        "known_limitations": [
            "2020-21 is a posthoc extension discovered after the h3 policy was selected",
            "pre-2020 training rows lack position/team, although player performance history exists",
            "historical fixture assignment retains final postponement scheduling",
            "chips are not replayed; both arms use chip_policy=none",
            "2022-23 remains excluded because its World Cup unlimited-transfer reset is unmodeled",
            "the five-season aggregate includes 2025-26, previously opened as temporal holdout",
        ],
    }
    destination = output / "manifest.json"
    if destination.exists():
        existing = json.loads(destination.read_text(encoding="utf-8"))
        without_time = lambda value: {
            key: item for key, item in value.items() if key != "created_at"
        }
        if without_time(existing) != without_time(payload):
            raise RuntimeError(
                "EXP-MOVA-2026-007 ya existe bajo otro código, dataset o evidencia padre"
            )
        return existing
    _write_json(destination, payload)
    return payload


def validate_historical_scoring(db_path: str | Path, output: Path,
                                manifest: dict) -> dict:
    columns = (
        "position, minutes, goals_scored, assists, clean_sheets, goals_conceded, "
        "own_goals, penalties_saved, penalties_missed, yellow_cards, red_cards, "
        "saves, bonus, total_points"
    )
    with sqlite3.connect(db_path) as connection:
        frame = pd.read_sql_query(
            f"SELECT {columns} FROM player_gameweek WHERE season = ?",
            connection,
            params=(TARGET_SEASON,),
        )
    if frame.empty:
        raise RuntimeError(f"no hay filas para {TARGET_SEASON}")
    if frame["position"].isna().any():
        raise RuntimeError(f"{TARGET_SEASON} contiene posiciones nulas")

    integer_fields = (
        "minutes", "goals_scored", "assists", "clean_sheets", "goals_conceded",
        "own_goals", "penalties_saved", "penalties_missed", "yellow_cards",
        "red_cards", "saves", "bonus",
    )
    reproduced = []
    for row in frame.itertuples(index=False):
        stats = PlayerStats(
            position=Position.parse(row.position),
            **{
                field: int(0 if pd.isna(getattr(row, field)) else getattr(row, field))
                for field in integer_fields
            },
        )
        reproduced.append(score(stats, TARGET_SEASON).total)
    actual = frame["total_points"].to_numpy(dtype=int)
    error = np.asarray(reproduced, dtype=int) - actual
    payload = {
        "experiment_id": manifest["experiment_id"],
        "source_sha256": manifest["source_sha256"],
        "dataset_sha256": manifest["dataset"]["sha256"],
        "season": TARGET_SEASON,
        "rows": int(len(frame)),
        "exact_rows": int(np.sum(error == 0)),
        "exact_rate": float(np.mean(error == 0)),
        "mae": float(np.mean(np.abs(error))),
        "max_abs_error": int(np.max(np.abs(error))),
        "accepted": bool(np.all(error == 0)),
    }
    _write_json(output / "historical-scoring-validation.json", payload)
    if not payload["accepted"]:
        raise RuntimeError("las reglas no reproducen exactamente los puntos 2020-21")
    return payload


def _load_parent_records(parent: Path, manifest: dict) -> list[dict]:
    records = []
    for season in PARENT_SEASONS:
        for variant in VARIANTS:
            path = parent / "replays" / f"{season}-{variant}.json"
            expected_sha = manifest["parent_evidence"]["files"][
                str(path.relative_to(parent))
            ]
            if _sha256(path) != expected_sha:
                raise RuntimeError(f"artefacto padre alterado: {path}")
            record = json.loads(path.read_text(encoding="utf-8"))
            if (record.get("season") != season or record.get("variant") != variant
                    or record.get("dataset_sha256") != manifest["dataset"]["sha256"]):
                raise RuntimeError(f"artefacto padre incompatible: {path}")
            records.append(record)
    return records


def summarize_extension(records: list[dict], output: Path, manifest: dict) -> dict:
    totals = pd.DataFrame([
        {"season": record["season"], "variant": record["variant"],
         "points": int(record["points"])}
        for record in records
    ])
    pivot = totals.pivot(index="season", columns="variant", values="points")
    deltas = (pivot["season_fixture_h3"] - pivot["control_h3"]).astype(int)
    baseline = pd.concat([
        pd.DataFrame(record["gameweeks"])[["gw", "points"]].assign(
            season=record["season"]
        )
        for record in records if record["variant"] == "control_h3"
    ], ignore_index=True)
    candidate = pd.concat([
        pd.DataFrame(record["gameweeks"])[["gw", "points"]].assign(
            season=record["season"]
        )
        for record in records if record["variant"] == "season_fixture_h3"
    ], ignore_index=True)
    bootstrap = paired_policy_bootstrap(
        baseline, candidate, draws=50_000, block_size=4, seed=42,
    )
    target_delta = int(deltas.loc[TARGET_SEASON])
    payload = {
        "experiment_id": manifest["experiment_id"],
        "source_sha256": manifest["source_sha256"],
        "dataset_sha256": manifest["dataset"]["sha256"],
        "posthoc_not_selection": True,
        "totals": totals.to_dict("records"),
        "delta_by_season": {str(key): int(value) for key, value in deltas.items()},
        "target_season_delta": target_delta,
        "wins": int((deltas > 0).sum()),
        "losses": int((deltas < 0).sum()),
        "mean_delta": float(deltas.mean()),
        "paired_bootstrap": bootstrap,
        "conclusion": "evidence_reinforced" if target_delta > 0 else "evidence_weakened",
        "selected_policy_unchanged": "season_fixture_h3",
        "promotion": "not_authorized",
    }
    _write_json(output / "historical-extension.json", payload)
    totals.to_csv(output / "historical-extension-totals.csv", index=False)
    return payload


def run_extension(args, output: Path, manifest: dict) -> dict:
    scoring = validate_historical_scoring(args.fpl_db, output, manifest)
    store = CachedStore(args.fpl_db)
    current = [
        run_variant(
            args, store, output, manifest, TARGET_SEASON, name,
            POLICY_VARIANTS[name], INHERITED_EVENT_WEIGHT,
        )
        for name in VARIANTS
    ]
    parent = _load_parent_records(Path(args.parent_output).resolve(), manifest)
    summary = summarize_extension(current + parent, output, manifest)
    return {"scoring_validation": scoring, "historical_extension": summary}


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("manifest", "run"))
    parser.add_argument("--fpl-db", required=True)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--parent-output", default=str(DEFAULT_PARENT_OUTPUT))
    parser.add_argument("--top-k", type=int, default=30)
    parser.add_argument("--time-limit", type=int, default=30)
    parser.add_argument("--force-models", action="store_true")
    parser.add_argument("--force-replays", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest = freeze_manifest(args, output)
    result = manifest if args.phase == "manifest" else run_extension(args, output, manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
