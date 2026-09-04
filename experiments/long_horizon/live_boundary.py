#!/usr/bin/env python3
"""Shadow vivo del estado de temporada seleccionado en EXP-MOVA-2026-013.

Solo consulta endpoints GET oficiales y escribe artefactos locales del sandbox.
No invoca la CLI productiva, no persiste trazas operativas y no puede escribir
en el equipo FPL.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from experiments.long_horizon.run import _git_sha, _sha256, _source_sha, _write_json
from mova_fpl.data import live
from mova_fpl.data.identity import player_key
from mova_fpl.data.private_state import validate as validate_private
from mova_fpl.data.schema import ALL_COLUMNS
from mova_fpl.data.sources import (
    FPL_BOOTSTRAP_URL,
    FPL_FIXTURES_URL,
    fetch_bootstrap,
    fetch_event_live,
    fetch_fixtures,
)
from mova_fpl.data.store import Store
from mova_fpl.engine.projection import fixture_horizon_projection
from mova_fpl.engine.runner import Config, decide
from mova_fpl.engine.simulator import _candidates
from mova_fpl.engine.state import State
from mova_fpl.models.features.minutes_features import build_targets
from mova_fpl.rules import get as get_rules


EXPERIMENT_ID = "EXP-MOVA-2026-014"
PARENT_EXPERIMENT_ID = "EXP-MOVA-2026-013"
TARGET_SEASON = "2026-27"
TARGET_GW = 3
CLOSED_GWS = (1, 2)
HIGHLIGHTS = ("erling haaland", "mamadou sangare")
DEFAULT_EXPERIMENTS = Path(__file__).resolve().parents[3] / "mova-fpl-experiments"
DEFAULT_OUTPUT = DEFAULT_EXPERIMENTS / EXPERIMENT_ID


def _bytes_sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _file_spec(path: Path) -> dict:
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    return {
        "path": str(resolved),
        "bytes": resolved.stat().st_size,
        "sha256": _sha256(resolved),
    }


def _write_new(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"input vivo inmutable ya existe: {path}")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


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
        "target": {"season": TARGET_SEASON, "gw": TARGET_GW},
        "closed_gws": list(CLOSED_GWS),
        "state_variants": {
            "control": "full 2025-26 only",
            "candidate": "full 2025-26 plus official settled GW1-GW2 2026-27",
        },
        "inputs": {
            "canonical_db": _file_spec(Path(args.fpl_db)),
            "minutes_model": _file_spec(Path(args.minutes_model)),
            "points_model": _file_spec(Path(args.points_model)),
            "private_team_state": _file_spec(Path(args.private_team_state)),
            "parent_external_evaluation": _file_spec(parent / "external-evaluation.json"),
        },
        "policy": {
            "name": "season_fixture_h3",
            "horizon": 3,
            "decay": 0.84,
            "chips": "disabled",
        },
        "pre_registered_checks": [
            "GW1 and GW2 must both be finished and data_checked",
            "all network calls use official GET primitives",
            "candidate history adds no GW3 rows",
            "Haaland and Sangare minute probabilities are reported before decisions",
            "both arms use identical roster, availability, fixtures, team state and models",
        ],
        "promotion": "forbidden; shadow evidence only",
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


def collect_inputs(output: Path, manifest: dict) -> dict:
    destination = output / "input-manifest.json"
    if destination.exists():
        return json.loads(destination.read_text(encoding="utf-8"))
    boot_raw = fetch_bootstrap()
    fixtures_raw = fetch_fixtures()
    event_raw = {gw: fetch_event_live(gw) for gw in CLOSED_GWS}
    boot = json.loads(boot_raw)
    events = {int(item["id"]): item for item in boot.get("events", ())}
    unsettled = [
        gw for gw in CLOSED_GWS
        if not (events.get(gw, {}).get("finished")
                and events.get(gw, {}).get("data_checked"))
    ]
    if unsettled:
        raise RuntimeError(f"jornadas aún no asentadas: {unsettled}")
    if events.get(TARGET_GW, {}).get("finished"):
        raise RuntimeError(f"GW{TARGET_GW} ya terminó; no es un shadow predeadline")

    raw = output / "raw"
    _write_new(raw / "bootstrap-static.json", boot_raw)
    _write_new(raw / "fixtures.json", fixtures_raw)
    for gw, payload in event_raw.items():
        _write_new(raw / f"event-live-gw{gw:02d}.json", payload)
    payload = {
        "experiment_id": manifest["experiment_id"],
        "source_sha256": manifest["source_sha256"],
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "network": "GET only",
        "files": {
            "bootstrap-static.json": {
                "url": FPL_BOOTSTRAP_URL, "sha256": _bytes_sha(boot_raw),
                "bytes": len(boot_raw),
            },
            "fixtures.json": {
                "url": FPL_FIXTURES_URL, "sha256": _bytes_sha(fixtures_raw),
                "bytes": len(fixtures_raw),
            },
            **{
                f"event-live-gw{gw:02d}.json": {
                    "url": (
                        "https://fantasy.premierleague.com/api/event/"
                        f"{gw}/live/"
                    ),
                    "sha256": _bytes_sha(item), "bytes": len(item),
                }
                for gw, item in event_raw.items()
            },
        },
        "settled_gws": list(CLOSED_GWS),
        "target_deadline": events[TARGET_GW].get("deadline_time"),
        "production_writes": 0,
    }
    _write_json(destination, payload)
    return payload


def _load_raw(output: Path, inputs: dict) -> tuple[dict, list, dict[int, dict]]:
    raw = output / "raw"
    payloads = {}
    for name, spec in inputs["files"].items():
        path = raw / name
        data = path.read_bytes()
        if _bytes_sha(data) != spec["sha256"]:
            raise RuntimeError(f"input vivo alterado: {path}")
        payloads[name] = json.loads(data)
    return (
        payloads["bootstrap-static.json"],
        payloads["fixtures.json"],
        {gw: payloads[f"event-live-gw{gw:02d}.json"] for gw in CLOSED_GWS},
    )


def build_closed_history(boot: dict, fixtures: list, events: dict[int, dict],
                         season: str = TARGET_SEASON) -> tuple[pd.DataFrame, dict]:
    """Normaliza event-live a filas causales suficientes para los modelos.

    El endpoint entrega estadísticas agregadas por GW. Por seguridad, este
    adaptador rechaza dobles jornadas: repartir un agregado entre dos fixtures
    inventaría datos. GW1-GW2 2026-27 tienen un solo partido por club.
    """
    clubs = live.teams(boot)
    positions = live.POSICIONES
    catalog = {int(item["id"]): item for item in boot.get("elements", ())}
    fixture_by_gw_team = {}
    fixture_by_id = {}
    for item in fixtures:
        event = item.get("event")
        if event not in events:
            continue
        fixture_by_id[int(item["id"])] = item
        for side in ("team_h", "team_a"):
            fixture_by_gw_team.setdefault(
                (int(event), int(item[side])), [],
            ).append(item)

    rows = []
    skipped_missing_catalog = 0
    for gw, payload in sorted(events.items()):
        for observed in payload.get("elements", ()):
            element = int(observed["id"])
            item = catalog.get(element)
            if item is None:
                skipped_missing_catalog += 1
                continue
            explanations = observed.get("explain") or ()
            explained = [int(record["fixture"]) for record in explanations]
            if len(set(explained)) > 1:
                raise RuntimeError(
                    f"GW{gw} contiene DGW para element={element}; no se desagrega"
                )
            team_id = int(item["team"])
            options = fixture_by_gw_team.get((int(gw), team_id), [])
            if len(options) != 1:
                raise RuntimeError(
                    f"calendario ambiguo GW{gw} team={team_id}: {len(options)} fixtures"
                )
            fixture = fixture_by_id.get(explained[0]) if explained else options[0]
            if fixture is None:
                raise RuntimeError(f"fixture explicado ausente para element={element}")
            home = team_id == int(fixture["team_h"])
            opponent = int(fixture["team_a"] if home else fixture["team_h"])
            name = f"{item.get('first_name', '')} {item.get('second_name', '')}".strip()
            row = {column: np.nan for column in ALL_COLUMNS}
            row.update({
                "season": season,
                "gw": int(gw),
                "element": element,
                "fixture": int(fixture["id"]),
                "player_key": player_key(name) or player_key(item.get("web_name", "")),
                "name": name or item.get("web_name", ""),
                "opponent_team": opponent,
                "was_home": int(home),
                "kickoff_time": fixture.get("kickoff_time"),
                "round": int(gw),
                "value": int(item["now_cost"]),
                "position": positions.get(int(item["element_type"])),
                "team": clubs.get(team_id, str(team_id)),
                "team_h_score": fixture.get("team_h_score"),
                "team_a_score": fixture.get("team_a_score"),
            })
            for key, value in (observed.get("stats") or {}).items():
                if key in row:
                    row[key] = value
            rows.append(row)
    frame = pd.DataFrame(rows, columns=ALL_COLUMNS)
    if not frame.empty and int(frame["gw"].max()) >= TARGET_GW:
        raise RuntimeError("historia viva contiene la jornada objetivo")
    quality = {
        "rows": int(len(frame)),
        "players": int(frame["player_key"].nunique()),
        "gws": sorted(int(value) for value in frame["gw"].unique()),
        "skipped_missing_current_catalog": int(skipped_missing_catalog),
        "duplicate_keys": int(frame.duplicated(["season", "gw", "element", "fixture"]).sum()),
    }
    if quality["gws"] != list(CLOSED_GWS) or quality["duplicate_keys"]:
        raise RuntimeError(f"historia viva inválida: {quality}")
    return frame, quality


def _decision_payload(decision, roster: pd.DataFrame) -> dict:
    names = roster.set_index("element")["name"].to_dict()
    return {
        "fingerprint": decision.fingerprint(),
        "expected_points": float(decision.expected_points),
        "transfers_in": [names.get(int(value), str(value)) for value in decision.transfers_in],
        "transfers_out": [names.get(int(value), str(value)) for value in decision.transfers_out],
        "hits": int(decision.hits),
        "captain": names.get(int(decision.captain), str(decision.captain)),
        "vice_captain": names.get(
            int(decision.vice_captain), str(decision.vice_captain),
        ),
        "starters": [names.get(int(value), str(value)) for value in decision.starters],
    }


def _arm(history: pd.DataFrame, roster: pd.DataFrame, boot: dict, fixtures: list,
         models: dict, team: dict) -> tuple[dict, pd.DataFrame]:
    schedule = live.fixture_schedule(fixtures, boot, TARGET_GW, TARGET_GW + 2)
    projection = fixture_horizon_projection(
        history=history,
        roster=roster,
        modelos=models,
        season=TARGET_SEASON,
        gw=TARGET_GW,
        horizon=3,
        schedule=schedule,
        decay=0.84,
        disponibilidad=roster["disponibilidad"].to_numpy(dtype=float),
    )
    current_xp = roster["element"].map(
        projection.horizon_xp[TARGET_GW],
    ).fillna(0.0)
    candidates = _candidates(roster, current_xp)
    rules = get_rules(TARGET_SEASON).SQUAD
    state = State(
        season=TARGET_SEASON,
        gw=TARGET_GW,
        candidates=candidates,
        squad=team["squad"],
        free_transfers=team["free_transfers"],
        bank=team["bank"],
        rules=rules,
        horizon_xp=projection.horizon_xp,
        horizon_sd=projection.horizon_sd,
        chips_allowed={},
    )
    config = Config(
        policy="milp", projector="points", model_version="1.1.0",
        horizon=3, decay=0.84, top_k=0, time_limit=600, chip_policy="none",
    )
    decision = decide(TARGET_GW, state, config)
    minute_features = build_targets(history, roster)
    minute_probability = models["minutes"].predict_proba_built(minute_features)
    detail = roster[["element", "player_key", "name", "position"]].copy()
    detail[["p0", "p1", "p60"]] = minute_probability
    detail["xp"] = current_xp.to_numpy(dtype=float)
    return {
        "history_rows": int(len(history)),
        "decision": _decision_payload(decision, roster),
        "config": asdict(config),
    }, detail


def run_shadow(args, output: Path, manifest: dict) -> dict:
    destination = output / "live-shadow.json"
    if destination.exists():
        existing = json.loads(destination.read_text(encoding="utf-8"))
        if existing.get("source_sha256") == manifest["source_sha256"]:
            return existing
        raise RuntimeError("live-shadow existente bajo otro código")
    inputs_path = output / "input-manifest.json"
    if not inputs_path.exists():
        raise FileNotFoundError("falta input-manifest.json; ejecute collect")
    inputs = json.loads(inputs_path.read_text(encoding="utf-8"))
    if inputs.get("source_sha256") != manifest["source_sha256"]:
        raise RuntimeError("inputs vivos no pertenecen al manifest")
    boot, fixtures, events = _load_raw(output, inputs)
    current, quality = build_closed_history(boot, fixtures, events)
    roster = live.roster(boot, fixtures, TARGET_SEASON, TARGET_GW)
    store = Store(manifest["inputs"]["canonical_db"]["path"])
    previous = store.as_of("2025-26", 39)
    candidate_history = pd.concat([previous, current], ignore_index=True)

    for key in ("minutes_model", "points_model", "private_team_state"):
        spec = manifest["inputs"][key]
        if _sha256(Path(spec["path"])) != spec["sha256"]:
            raise RuntimeError(f"input alterado: {key}")
    models = {
        "minutes": joblib.load(manifest["inputs"]["minutes_model"]["path"]),
        "points": joblib.load(manifest["inputs"]["points_model"]["path"]),
    }
    private = json.loads(
        Path(manifest["inputs"]["private_team_state"]["path"]).read_text()
    )
    normalized, team_quality = validate_private(
        private, expected_team_id=int(private["team_id"]),
    )
    squad, blank = live.squad_from_private(normalized, roster, boot)
    team = {
        "squad": squad,
        "bank": squad.bank,
        "free_transfers": int(team_quality["free_transfers"]),
        "blank_players": blank,
        "fingerprint": team_quality["fingerprint"],
    }
    control, control_detail = _arm(
        previous, roster, boot, fixtures, models, team,
    )
    candidate, candidate_detail = _arm(
        candidate_history, roster, boot, fixtures, models, team,
    )
    merged = control_detail.merge(
        candidate_detail,
        on=["element", "player_key", "name", "position"],
        suffixes=("_control", "_candidate"),
    )
    for metric in ("p0", "p1", "p60", "xp"):
        merged[f"{metric}_delta"] = (
            merged[f"{metric}_candidate"] - merged[f"{metric}_control"]
        )
    highlights = merged[merged["player_key"].isin(HIGHLIGHTS)].copy()
    payload = {
        "experiment_id": manifest["experiment_id"],
        "source_sha256": manifest["source_sha256"],
        "input_manifest_sha256": _sha256(inputs_path),
        "season": TARGET_SEASON,
        "gw": TARGET_GW,
        "deadline": inputs["target_deadline"],
        "history_quality": quality,
        "team_state": {
            "free_transfers": team["free_transfers"],
            "bank": team["bank"],
            "fingerprint": team["fingerprint"],
            "blank_players": team["blank_players"],
        },
        "control": control,
        "candidate": candidate,
        "comparison": {
            "decision_changed": (
                control["decision"]["fingerprint"]
                != candidate["decision"]["fingerprint"]
            ),
            "expected_points_delta": (
                candidate["decision"]["expected_points"]
                - control["decision"]["expected_points"]
            ),
            "highlights": highlights.to_dict("records"),
        },
        "safety": {
            "network": "official GET only",
            "production_writes": 0,
            "fpl_writes": 0,
            "selected_for_execution": False,
            "promotion": "not_authorized",
        },
    }
    merged.to_csv(output / "player-state-comparison.csv", index=False)
    _write_json(destination, payload)
    return payload


def parse_args():
    main_repo = Path(__file__).resolve().parents[3] / "mova-pro-futbol-data-analytics"
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("manifest", "collect", "run"))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--parent-output", default=str(DEFAULT_EXPERIMENTS / PARENT_EXPERIMENT_ID))
    parser.add_argument("--fpl-db", default=str(main_repo / "data/processed/fpl_canonical.db"))
    parser.add_argument("--minutes-model", default=str(main_repo / "models/minutes/minutes-1.1.0.joblib"))
    parser.add_argument("--points-model", default=str(main_repo / "models/points/points-1.1.0.joblib"))
    parser.add_argument(
        "--private-team-state",
        default=str(DEFAULT_EXPERIMENTS / "EXP-MOVA-2026-008/team-state/team-state.json"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest = freeze_manifest(args, output)
    if args.phase == "manifest":
        result = manifest
    elif args.phase == "collect":
        result = collect_inputs(output, manifest)
    else:
        result = run_shadow(args, output, manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
