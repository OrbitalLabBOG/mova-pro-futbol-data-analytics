#!/usr/bin/env python3
"""Ablation causal de proxies de eventos sobre la politica h3 ganadora.

EXP-MOVA-2026-003 probo ``threat`` y ``creativity`` solo junto al horizonte
seis. Este experimento separa ambas variables: conserva calendario, estado,
horizonte y optimizador de ``season_fixture_h3`` y cambia unicamente el modelo
de goles/asistencias. El peso 0.45 queda heredado y congelado antes de mirar la
evaluacion temporal 2025-26.
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
    HOLDOUT_SEASON,
    INHERITED_EVENT_WEIGHT,
    POLICY_VARIANTS,
    SELECTION_SEASONS,
    _git_sha,
    _model_source_sha,
    _sha256,
    _source_sha,
    _write_json,
    run_variant,
)


EXPERIMENT_ID = "EXP-MOVA-2026-004"
PARENT_EXPERIMENT_ID = "EXP-MOVA-2026-003"
DEFAULT_OUTPUT = (Path(__file__).resolve().parents[3] / "mova-fpl-experiments"
                  / EXPERIMENT_ID)

VARIANTS = {
    "control_h3": dict(POLICY_VARIANTS["control_h3"]),
    "season_fixture_h3": dict(POLICY_VARIANTS["season_fixture_h3"]),
    "season_fixture_h3_events": {
        **POLICY_VARIANTS["season_fixture_h3"],
        "events": True,
    },
}


def freeze_manifest(args, output: Path) -> dict:
    root = Path(__file__).resolve().parents[2]
    db = Path(args.fpl_db).resolve()
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
        "dataset": {"path": str(db), "bytes": db.stat().st_size,
                    "sha256": _sha256(db)},
        "development_seasons": SELECTION_SEASONS,
        "external_evaluation_season": HOLDOUT_SEASON,
        "variants": VARIANTS,
        "controlled_variable": "threat/creativity event proxy in goals+assists rate",
        "event_proxy_weight": INHERITED_EVENT_WEIGHT,
        "event_proxy_weight_source": (
            "frozen selection in EXP-MOVA-2026-001/002; not tuned in this experiment"
        ),
        "north_star": "PVA-38 paired season points",
        "challenger_gate": (
            "events must beat season_fixture_h3 mean and win at least 2/3 paired "
            "development seasons"
        ),
        "promotion": "forbidden; external evaluation and live shadow required",
        "known_limitations": [
            "2025-26 was already visible in the parent policy experiment, so it is an "
            "external temporal evaluation rather than a cognitively pristine holdout",
            "threat and creativity are FPL-native event aggregates, not raw Opta events",
            "historical fixture assignment retains final postponement scheduling",
        ],
    }
    destination = output / "manifest.json"
    if destination.exists():
        existing = json.loads(destination.read_text(encoding="utf-8"))
        comparable_existing = {key: value for key, value in existing.items()
                               if key != "created_at"}
        comparable_new = {key: value for key, value in payload.items()
                          if key != "created_at"}
        if comparable_existing != comparable_new:
            raise RuntimeError(
                "el manifest EXP-MOVA-2026-004 ya existe bajo otro codigo o dataset"
            )
        return existing
    _write_json(destination, payload)
    return payload


def _gameweeks(record: dict) -> pd.DataFrame:
    return pd.DataFrame(record["gameweeks"])[["gw", "points"]].assign(
        season=record["season"]
    )


def summarize_development(records: list[dict], output: Path, manifest: dict) -> dict:
    totals = pd.DataFrame([
        {"season": record["season"], "variant": record["variant"],
         "points": int(record["points"])}
        for record in records
    ])
    pivot = totals.pivot(index="season", columns="variant", values="points")
    incumbent = "season_fixture_h3"
    challenger = "season_fixture_h3_events"
    deltas = (pivot[challenger] - pivot[incumbent]).astype(int)
    wins = int((deltas > 0).sum())
    mean_delta = float(deltas.mean())
    selected = challenger if mean_delta > 0 and wins >= 2 else incumbent

    by_variant = {}
    baseline = pd.concat([
        _gameweeks(record) for record in records if record["variant"] == "control_h3"
    ], ignore_index=True)
    for name in (incumbent, challenger):
        candidate = pd.concat([
            _gameweeks(record) for record in records if record["variant"] == name
        ], ignore_index=True)
        by_variant[name] = paired_policy_bootstrap(baseline, candidate)

    incumbent_gw = pd.concat([
        _gameweeks(record) for record in records if record["variant"] == incumbent
    ], ignore_index=True)
    challenger_gw = pd.concat([
        _gameweeks(record) for record in records if record["variant"] == challenger
    ], ignore_index=True)
    versus_incumbent = paired_policy_bootstrap(incumbent_gw, challenger_gw)
    payload = {
        "experiment_id": manifest["experiment_id"],
        "source_sha256": manifest["source_sha256"],
        "dataset_sha256": manifest["dataset"]["sha256"],
        "selection_only": True,
        "totals": totals.to_dict("records"),
        "mean_points": {
            str(key): float(value)
            for key, value in totals.groupby("variant")["points"].mean().items()
        },
        "event_delta_vs_incumbent_by_season": {
            str(key): int(value) for key, value in deltas.items()
        },
        "event_wins_vs_incumbent": wins,
        "event_mean_delta_vs_incumbent": mean_delta,
        "paired_vs_control": by_variant,
        "paired_events_vs_incumbent": versus_incumbent,
        "selected_policy": selected,
        "challenger_accepted": selected == challenger,
        "selection_rule": manifest["challenger_gate"],
    }
    _write_json(output / "policy-selection.json", payload)
    totals.to_csv(output / "policy-selection-totals.csv", index=False)
    return payload


def select_policy(args, store: CachedStore, output: Path, manifest: dict) -> dict:
    records = []
    for season in SELECTION_SEASONS:
        for name, spec in VARIANTS.items():
            records.append(run_variant(
                args, store, output, manifest, season, name, spec,
                INHERITED_EVENT_WEIGHT,
            ))
    return summarize_development(records, output, manifest)


def external_evaluation(args, store: CachedStore, output: Path,
                        manifest: dict) -> dict:
    selection_path = output / "policy-selection.json"
    if not selection_path.exists():
        raise FileNotFoundError("falta policy-selection.json; ejecute select primero")
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    if (selection.get("source_sha256") != manifest["source_sha256"]
            or selection.get("dataset_sha256") != manifest["dataset"]["sha256"]):
        raise RuntimeError("la seleccion no pertenece al manifest vigente")
    challenger = "season_fixture_h3_events"
    if selection.get("selected_policy") != challenger:
        raise RuntimeError(
            "el challenger de eventos no supero desarrollo; evaluacion externa sellada"
        )
    destination = output / "external-evaluation.json"
    if destination.exists():
        sealed = json.loads(destination.read_text(encoding="utf-8"))
        if (sealed.get("source_sha256") == manifest["source_sha256"]
                and sealed.get("dataset_sha256") == manifest["dataset"]["sha256"]):
            return sealed
        raise RuntimeError("la evaluacion ya fue abierta bajo otro codigo; cree otro experimento")

    records = [
        run_variant(args, store, output, manifest, HOLDOUT_SEASON, name, spec,
                    INHERITED_EVENT_WEIGHT)
        for name, spec in VARIANTS.items()
    ]
    points = {record["variant"]: int(record["points"]) for record in records}
    payload = {
        "experiment_id": manifest["experiment_id"],
        "source_sha256": manifest["source_sha256"],
        "dataset_sha256": manifest["dataset"]["sha256"],
        "season": HOLDOUT_SEASON,
        "points": points,
        "event_delta_vs_incumbent": (
            points[challenger] - points["season_fixture_h3"]
        ),
        "promotion": "not_authorized",
    }
    _write_json(destination, payload)
    return payload


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("manifest", "select", "external-evaluation"))
    parser.add_argument("--fpl-db", required=True)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
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
    if args.phase == "manifest":
        result = manifest
    else:
        store = CachedStore(args.fpl_db)
        if args.phase == "select":
            result = select_policy(args, store, output, manifest)
        else:
            result = external_evaluation(args, store, output, manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
