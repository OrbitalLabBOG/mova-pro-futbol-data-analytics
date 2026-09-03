#!/usr/bin/env python3
"""EXP012: valor terminal de transferencias libres en el horizonte h3.

El challenger no alarga el horizonte ni cambia xP. Añade un único valor de
continuación preregistrado a las FT disponibles después de la última jornada
modelada, para reducir el sesgo de truncamiento del rolling horizon.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

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


EXPERIMENT_ID = "EXP-MOVA-2026-012"
POLICY_NAME = "season_fixture_h3_terminal_ft_v1"
TERMINAL_FT_VALUE = 1.0
DEVELOPMENT_SEASONS = ("2020-21", "2021-22", "2023-24", "2024-25")
EXTERNAL_SEASON = "2025-26"
DEFAULT_EXPERIMENTS = Path(__file__).resolve().parents[3] / "mova-fpl-experiments"
DEFAULT_OUTPUT = DEFAULT_EXPERIMENTS / EXPERIMENT_ID
DEFAULT_PARENT = DEFAULT_EXPERIMENTS / "EXP-MOVA-2026-003"
DEFAULT_PARENT_2020 = DEFAULT_EXPERIMENTS / "EXP-MOVA-2026-007"

TERMINAL_SPEC = {
    **POLICY_VARIANTS["season_fixture_h3"],
    "terminal_free_transfer_value": TERMINAL_FT_VALUE,
}


def _parent_record(args, season: str) -> Path:
    parent = Path(args.parent_2020 if season == "2020-21" else args.parent).resolve()
    return parent / "replays" / f"{season}-season_fixture_h3.json"


def freeze_manifest(args, output: Path) -> dict:
    root = Path(__file__).resolve().parents[2]
    db = Path(args.fpl_db).resolve()
    records = {
        season: _parent_record(args, season)
        for season in (*DEVELOPMENT_SEASONS, EXTERNAL_SEASON)
    }
    missing = [str(path) for path in records.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"faltan replays incumbent: {missing}")
    payload = {
        "experiment_id": EXPERIMENT_ID,
        "parent_experiment_ids": ["EXP-MOVA-2026-003", "EXP-MOVA-2026-007",
                                  "EXP-MOVA-2026-011"],
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_sha": _git_sha(root),
        "source_sha256": _source_sha(root),
        "model_source_sha256": _model_source_sha(root),
        "branch": subprocess.run(
            ["git", "branch", "--show-current"], cwd=root, check=True,
            capture_output=True, text=True,
        ).stdout.strip(),
        "dataset": {"path": str(db), "bytes": db.stat().st_size,
                    "sha256": _sha256(db)},
        "incumbent_inputs": {
            season: {"path": str(path), "bytes": path.stat().st_size,
                     "sha256": _sha256(path)}
            for season, path in records.items()
        },
        "development_seasons": list(DEVELOPMENT_SEASONS),
        "external_evaluation_season": EXTERNAL_SEASON,
        "incumbent": "season_fixture_h3",
        "challenger": TERMINAL_SPEC,
        "terminal_value_rationale": (
            "one preregistered point per ending FT: 25% of the four-point hard hit "
            "cost; no value sweep"
        ),
        "selection_gate": "positive mean PVA and wins in at least 3/4 development seasons",
        "north_star": "incremental PVA-38 versus season_fixture_h3",
        "research_basis": [
            "https://arxiv.org/abs/2210.00491",
            "https://www.premierleague.com/en/news/2174907",
        ],
        "promotion": "forbidden; live causal evidence and explicit approval required",
        "known_limitations": [
            "the terminal approximation values FT inventory, not the full future squad state",
            "the one-point value is structural and preregistered, not empirically tuned",
            "2025-26 was previously observed and is only a mechanical external evaluation",
            "2022-23 remains excluded because its unlimited-transfer reset is unmodeled",
            "chips remain disabled symmetrically",
        ],
    }
    destination = output / "manifest.json"
    if destination.exists():
        existing = json.loads(destination.read_text(encoding="utf-8"))
        without_time = lambda row: {
            key: value for key, value in row.items() if key != "created_at"
        }
        if without_time(existing) != without_time(payload):
            raise RuntimeError("EXP012 ya existe bajo otros inputs o código")
        return existing
    _write_json(destination, payload)
    return payload


def _load_incumbent(manifest: dict, season: str) -> dict:
    spec = manifest["incumbent_inputs"][season]
    path = Path(spec["path"])
    if _sha256(path) != spec["sha256"]:
        raise RuntimeError(f"replay incumbent alterado: {season}")
    record = json.loads(path.read_text(encoding="utf-8"))
    if (record.get("season") != season
            or record.get("variant") != "season_fixture_h3"
            or record.get("dataset_sha256") != manifest["dataset"]["sha256"]):
        raise RuntimeError(f"replay incumbent incompatible: {season}")
    return record


def _gameweeks(record: dict) -> pd.DataFrame:
    return pd.DataFrame(record["gameweeks"])[["gw", "points"]].assign(
        season=record["season"]
    )


def summarize(records: list[dict], output: Path, manifest: dict, *,
              external: bool = False) -> dict:
    totals = pd.DataFrame([
        {"season": record["season"], "variant": record["variant"],
         "points": int(record["points"])}
        for record in records
    ])
    pivot = totals.pivot(index="season", columns="variant", values="points")
    deltas = (pivot[POLICY_NAME] - pivot["season_fixture_h3"]).astype(int)
    baseline = pd.concat([
        _gameweeks(record) for record in records
        if record["variant"] == "season_fixture_h3"
    ], ignore_index=True)
    challenger = pd.concat([
        _gameweeks(record) for record in records if record["variant"] == POLICY_NAME
    ], ignore_index=True)
    wins = int((deltas > 0).sum())
    required_wins = 1 if external else 3
    accepted = bool(float(deltas.mean()) > 0 and wins >= required_wins)
    payload = {
        "experiment_id": manifest["experiment_id"],
        "source_sha256": manifest["source_sha256"],
        "dataset_sha256": manifest["dataset"]["sha256"],
        "external_evaluation": bool(external),
        "totals": totals.to_dict("records"),
        "delta_by_season": {str(key): int(value) for key, value in deltas.items()},
        "mean_delta": float(deltas.mean()),
        "wins": wins,
        "required_wins": required_wins,
        "paired_bootstrap": paired_policy_bootstrap(
            baseline, challenger, draws=50_000, block_size=4, seed=42,
        ),
        "challenger_accepted": accepted,
        "selected_policy": POLICY_NAME if accepted else "season_fixture_h3",
        "promotion": "not_authorized",
    }
    name = "external-evaluation.json" if external else "selection.json"
    _write_json(output / name, payload)
    totals.to_csv(output / name.replace(".json", "-totals.csv"), index=False)
    return payload


def select(args, store: CachedStore, output: Path, manifest: dict) -> dict:
    records = []
    for season in DEVELOPMENT_SEASONS:
        records.append(_load_incumbent(manifest, season))
        records.append(run_variant(
            args, store, output, manifest, season, POLICY_NAME, TERMINAL_SPEC,
            INHERITED_EVENT_WEIGHT,
        ))
    return summarize(records, output, manifest)


def external_evaluation(args, store: CachedStore, output: Path,
                        manifest: dict) -> dict:
    selection_path = output / "selection.json"
    if not selection_path.is_file():
        raise FileNotFoundError("falta selection.json; ejecute select primero")
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    if (selection.get("source_sha256") != manifest["source_sha256"]
            or not selection.get("challenger_accepted")):
        raise RuntimeError("el challenger no superó desarrollo; evaluación externa sellada")
    destination = output / "external-evaluation.json"
    if destination.exists():
        existing = json.loads(destination.read_text(encoding="utf-8"))
        if (existing.get("source_sha256") == manifest["source_sha256"]
                and existing.get("dataset_sha256") == manifest["dataset"]["sha256"]):
            return existing
        raise RuntimeError("evaluación externa ya abierta bajo otro código")
    records = [
        _load_incumbent(manifest, EXTERNAL_SEASON),
        run_variant(
            args, store, output, manifest, EXTERNAL_SEASON, POLICY_NAME,
            TERMINAL_SPEC, INHERITED_EVENT_WEIGHT,
        ),
    ]
    return summarize(records, output, manifest, external=True)


def parse_args(argv: list[str] | None = None):
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("manifest", "select", "external-evaluation"))
    parser.add_argument("--fpl-db", required=True)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--parent", default=str(DEFAULT_PARENT))
    parser.add_argument("--parent-2020", default=str(DEFAULT_PARENT_2020))
    parser.add_argument("--top-k", type=int, default=30)
    parser.add_argument("--time-limit", type=int, default=30)
    parser.add_argument("--force-models", action="store_true")
    parser.add_argument("--force-replays", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest = freeze_manifest(args, output)
    if args.phase == "manifest":
        print(json.dumps(manifest, indent=2))
        return
    store = CachedStore(args.fpl_db)
    result = (
        select(args, store, output, manifest)
        if args.phase == "select"
        else external_evaluation(args, store, output, manifest)
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
