#!/usr/bin/env python3
"""Shadow predeadline del ensemble de regimen seleccionado en EXP-017.

Consume un snapshot oficial inmutable y un estado privado sanitizado. No hace
red, no persiste trazas operativas y no puede escribir en FPL.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from experiments.long_horizon.forecast_ensemble import ForecastEnsembleProjector
from experiments.long_horizon.run import _git_sha, _sha256, _source_sha, _write_json
from experiments.long_horizon.season_boundary import _file_spec
from mova_fpl.cli.live import _engine_violations
from mova_fpl.data import live
from mova_fpl.data.private_state import validate as validate_private
from mova_fpl.data.snapshot import (
    load_element_summaries,
    load_event_history,
    load_snapshot,
)
from mova_fpl.data.store import Store
from mova_fpl.engine.projection import fixture_horizon_projection
from mova_fpl.engine.runner import Config, decide
from mova_fpl.engine.simulator import _candidates
from mova_fpl.engine.state import State
from mova_fpl.models.features.minutes_features import build_targets
from mova_fpl.rules import get as get_rules


EXPERIMENT_ID = "EXP-MOVA-2026-020"
PARENT_EXPERIMENT_ID = "EXP-MOVA-2026-017"
DEFAULT_EXPERIMENTS = Path(__file__).resolve().parents[3] / "mova-fpl-experiments"
DEFAULT_OUTPUT = DEFAULT_EXPERIMENTS / EXPERIMENT_ID


def freeze_manifest(args, output: Path) -> dict:
    root = Path(__file__).resolve().parents[2]
    parent = Path(args.parent_output).resolve()
    snapshot = Path(args.snapshot_dir).resolve()
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
        "target": {"season": args.season, "gw": int(args.gw)},
        "alpha_full": 0.5,
        "inputs": {
            "snapshot_manifest": _file_spec(snapshot / "manifest.json"),
            "canonical_db": _file_spec(Path(args.fpl_db)),
            "minutes_model": _file_spec(Path(args.minutes_model)),
            "points_model": _file_spec(Path(args.points_model)),
            "private_team_state": _file_spec(Path(args.private_team_state)),
            "parent_external_evaluation": _file_spec(
                parent / "external-evaluation.json"
            ),
            "operational_shadow": _file_spec(Path(args.operational_shadow)),
        },
        "snapshot_dir": str(snapshot),
        "policy": {"name": "season_fixture_h3", "horizon": 3,
                   "decay": 0.84, "chips": "disabled"},
        "safety": {
            "network": "none",
            "production_writes": 0,
            "fpl_writes": 0,
            "selected_for_execution": False,
        },
        "promotion": "forbidden; one live shadow observation only",
    }
    destination = output / "manifest.json"
    if destination.exists():
        existing = json.loads(destination.read_text(encoding="utf-8"))
        strip_time = lambda value: {k: v for k, v in value.items() if k != "created_at"}
        if strip_time(existing) != strip_time(payload):
            raise RuntimeError(f"{EXPERIMENT_ID} ya existe bajo otros inputs")
        return existing
    _write_json(destination, payload)
    return payload


def _verify(spec: dict) -> Path:
    path = Path(spec["path"])
    if not path.is_file() or _sha256(path) != spec["sha256"]:
        raise RuntimeError(f"input ausente o alterado: {path}")
    return path


def _decision_payload(decision, roster: pd.DataFrame, state: State) -> dict:
    names = roster.set_index("element")["name"].to_dict()
    return {
        "decision": decision.to_dict(),
        "transfers_in_names": [names.get(int(x), str(x)) for x in decision.transfers_in],
        "transfers_out_names": [names.get(int(x), str(x)) for x in decision.transfers_out],
        "captain_name": names.get(int(decision.captain), str(decision.captain)),
        "vice_captain_name": names.get(
            int(decision.vice_captain), str(decision.vice_captain)
        ),
        "violations": _engine_violations(decision, state),
    }


def _projection(history, roster, models, schedule, season, gw):
    return fixture_horizon_projection(
        history=history,
        roster=roster,
        modelos=models,
        season=season,
        gw=gw,
        horizon=3,
        schedule=schedule,
        decay=0.84,
        disponibilidad=roster["disponibilidad"].to_numpy(dtype=float),
    )


def run_shadow(args, output: Path, manifest: dict) -> dict:
    destination = output / "live-shadow.json"
    if destination.exists():
        existing = json.loads(destination.read_text(encoding="utf-8"))
        if existing.get("source_sha256") == manifest["source_sha256"]:
            return existing
        raise RuntimeError("live shadow existente bajo otro codigo")
    for spec in manifest["inputs"].values():
        _verify(spec)
    snapshot = Path(manifest["snapshot_dir"])
    boot, fixtures, snapshot_manifest = load_snapshot(snapshot)
    events = load_event_history(snapshot, boot, args.gw)
    element_summaries = load_element_summaries(
        snapshot, boot, fixtures, events,
    )
    current, quality = live.closed_history(
        boot, fixtures, events, args.season, args.gw,
        element_summaries=element_summaries,
    )
    previous = Store(manifest["inputs"]["canonical_db"]["path"]).as_of(
        "2025-26", 39,
    )
    full = pd.concat([previous, current], ignore_index=True)
    roster = live.roster(boot, fixtures, args.season, args.gw)
    schedule = live.fixture_schedule(fixtures, boot, args.gw, args.gw + 2)
    models = {
        "minutes": joblib.load(manifest["inputs"]["minutes_model"]["path"]),
        "points": joblib.load(manifest["inputs"]["points_model"]["path"]),
    }
    full_projection = _projection(
        full, roster, models, schedule, args.season, args.gw,
    )
    reset_projection = _projection(
        current, roster, models, schedule, args.season, args.gw,
    )
    alpha = float(manifest["alpha_full"])
    horizon_xp = {}
    horizon_sd = {}
    for target_gw in range(args.gw, args.gw + 3):
        horizon_xp[target_gw] = ForecastEnsembleProjector._blend_map(
            full_projection.horizon_xp[target_gw],
            reset_projection.horizon_xp[target_gw],
            alpha,
        )
        horizon_sd[target_gw] = {}
        for element, mean in horizon_xp[target_gw].items():
            full_mean = float(full_projection.horizon_xp[target_gw].get(element, 0.0))
            reset_mean = float(reset_projection.horizon_xp[target_gw].get(element, 0.0))
            full_sd = float(full_projection.horizon_sd[target_gw].get(element, 0.0))
            reset_sd = float(reset_projection.horizon_sd[target_gw].get(element, 0.0))
            second = (
                alpha * (full_sd ** 2 + full_mean ** 2)
                + (1.0 - alpha) * (reset_sd ** 2 + reset_mean ** 2)
            )
            horizon_sd[target_gw][element] = float(
                np.sqrt(max(0.0, second - float(mean) ** 2))
            )

    private = json.loads(
        Path(manifest["inputs"]["private_team_state"]["path"]).read_text()
    )
    normalized, team_quality = validate_private(
        private, expected_team_id=int(private["team_id"]),
    )
    squad, blank = live.squad_from_private(normalized, roster, boot)
    rules = get_rules(args.season).SQUAD
    config = Config(
        policy="milp", projector="points", model_version="1.1.0",
        horizon=3, decay=0.84, top_k=0, time_limit=600, chip_policy="none",
    )

    def make_state(projection_xp, projection_sd):
        xp = roster["element"].map(projection_xp[args.gw]).fillna(0.0)
        return State(
            season=args.season, gw=args.gw, candidates=_candidates(roster, xp),
            squad=squad, free_transfers=int(team_quality["free_transfers"]),
            bank=squad.bank, rules=rules, horizon_xp=projection_xp,
            horizon_sd=projection_sd, chips_allowed={},
        )

    control_state = make_state(
        full_projection.horizon_xp, full_projection.horizon_sd,
    )
    ensemble_state = make_state(horizon_xp, horizon_sd)
    control_decision = decide(args.gw, control_state, config)
    ensemble_decision = decide(args.gw, ensemble_state, config)

    probability_full = models["minutes"].predict_proba_built(
        build_targets(full, roster)
    )
    probability_reset = models["minutes"].predict_proba_built(
        build_targets(current, roster)
    )
    probability_blend = alpha * probability_full + (1.0 - alpha) * probability_reset
    detail = roster[["element", "player_key", "name", "position", "team"]].copy()
    detail["p60_full"] = probability_full[:, 2]
    detail["p60_reset"] = probability_reset[:, 2]
    detail["p60_blend"] = probability_blend[:, 2]
    detail["xp_full"] = detail["element"].map(
        full_projection.horizon_xp[args.gw]).fillna(0.0)
    detail["xp_reset"] = detail["element"].map(
        reset_projection.horizon_xp[args.gw]).fillna(0.0)
    detail["xp_blend"] = detail["element"].map(horizon_xp[args.gw]).fillna(0.0)
    detail["regime_disagreement"] = (detail["xp_full"] - detail["xp_reset"]).abs()
    detail = detail.sort_values("regime_disagreement", ascending=False)

    operational = json.loads(
        Path(manifest["inputs"]["operational_shadow"]["path"]).read_text()
    )
    payload = {
        "experiment_id": EXPERIMENT_ID,
        "source_sha256": manifest["source_sha256"],
        "season": args.season,
        "gw": int(args.gw),
        "deadline": snapshot_manifest["deadline_time"],
        "history": {
            "previous_rows": int(len(previous)),
            "current": quality,
            "ensemble_alpha_full": alpha,
        },
        "team_state": {
            "fingerprint": team_quality["fingerprint"],
            "free_transfers": int(team_quality["free_transfers"]),
            "bank": float(squad.bank),
            "blank_players": blank,
        },
        "control_full": _decision_payload(control_decision, roster, control_state),
        "candidate_ensemble": _decision_payload(
            ensemble_decision, roster, ensemble_state,
        ),
        "comparison": {
            "decision_changed": (
                control_decision.fingerprint() != ensemble_decision.fingerprint()
            ),
            "current_gw_expected_points_delta": round(
                ensemble_decision.expected_points - control_decision.expected_points, 3
            ),
            "top_regime_disagreements": detail.head(20).to_dict("records"),
        },
        "operational_selected_candidate": {
            "candidate_key": operational.get("selected_candidate_key"),
            "decision": next(
                row["decision"] for row in operational.get("candidates", [])
                if row.get("candidate_key") == operational.get("selected_candidate_key")
            ),
        },
        "config": asdict(config),
        "safety": manifest["safety"],
        "promotion": "not_authorized; collect consecutive live shadows",
    }
    detail.to_csv(output / "player-comparison.csv", index=False)
    _write_json(destination, payload)
    return payload


def parse_args():
    main_repo = Path(__file__).resolve().parents[3] / "mova-pro-futbol-data-analytics"
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("manifest", "run"))
    parser.add_argument("--season", default="2026-27")
    parser.add_argument("--gw", type=int, default=3)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--parent-output", default=str(DEFAULT_EXPERIMENTS / PARENT_EXPERIMENT_ID),
    )
    parser.add_argument(
        "--snapshot-dir",
        default=str(DEFAULT_EXPERIMENTS / (
            "EXP-MOVA-2026-019/snapshots/2026-27/gw03/20260904T054838Z"
        )),
    )
    parser.add_argument(
        "--fpl-db", default=str(main_repo / "data/processed/fpl_canonical.db"),
    )
    parser.add_argument(
        "--minutes-model", default=str(main_repo / "models/minutes/minutes-1.1.0.joblib"),
    )
    parser.add_argument(
        "--points-model", default=str(main_repo / "models/points/points-1.1.0.joblib"),
    )
    parser.add_argument(
        "--private-team-state",
        default=str(DEFAULT_EXPERIMENTS / "EXP-MOVA-2026-008/team-state/team-state.json"),
    )
    parser.add_argument(
        "--operational-shadow",
        default=str(DEFAULT_EXPERIMENTS / "EXP-MOVA-2026-019/gw03-promotable.json"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest = freeze_manifest(args, output)
    result = manifest if args.phase == "manifest" else run_shadow(args, output, manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
