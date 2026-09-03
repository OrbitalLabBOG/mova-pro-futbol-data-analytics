#!/usr/bin/env python3
"""Recourse estocástico discreto sobre la política fixture-h3.

La media de xP permanece congelada. La única variable nueva es cómo se valora
la primera plantilla frente a futuros posibles: se muestrean PMFs discretas,
se fija la acción de hoy y cada escenario vuelve a optimizar GW+1/GW+2. Así la
incertidumbre puede aportar valor de opción sin premiar o castigar varianza por
sí misma.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import Counter
from dataclasses import replace
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
from mova_fpl.engine.policies import POLICIES, optimizer_config
from mova_fpl.engine.projection import fixture_horizon_projection
from mova_fpl.engine.runner import decide
from mova_fpl.engine.simulator import ProjectionBundle
from mova_fpl.engine.state import Candidate, Decision, State
from mova_fpl.optimizer import FirstStage, solve
from mova_fpl.rules.base import Position
from mova_fpl.rules.money import to_millions, to_tenths
from mova_fpl.engine.discrete_uncertainty import SUPPORT, knn_discrete_pmf


EXPERIMENT_ID = "EXP-MOVA-2026-009"
PARENT_POLICY_EXPERIMENT = "EXP-MOVA-2026-003"
PARENT_UNCERTAINTY_EXPERIMENT = "EXP-MOVA-2026-005"
POLICY_NAME = "stochastic-recourse-h3"
SCENARIO_COUNT = 6
MAX_FIRST_STAGE_CANDIDATES = 3
MIN_RECOURSE_GAIN = 0.10
NEIGHBORS = 200
PRIOR_STRENGTH = 0.0
DEVELOPMENT_SEASONS = ("2021-22", "2023-24", "2024-25")
EXTERNAL_SEASON = "2025-26"
CALIBRATION_SEASONS = ("2020-21", "2021-22", "2023-24", "2024-25")

DEFAULT_EXPERIMENTS = Path(__file__).resolve().parents[3] / "mova-fpl-experiments"
DEFAULT_OUTPUT = DEFAULT_EXPERIMENTS / EXPERIMENT_ID
DEFAULT_POLICY_PARENT = DEFAULT_EXPERIMENTS / PARENT_POLICY_EXPERIMENT
DEFAULT_2020_PARENT = DEFAULT_EXPERIMENTS / "EXP-MOVA-2026-007"

RECOURSE_SPEC = {
    **POLICY_VARIANTS["season_fixture_h3"],
    "policy": POLICY_NAME,
    "scenario_count": SCENARIO_COUNT,
    "max_first_stage_candidates": MAX_FIRST_STAGE_CANDIDATES,
    "minimum_recourse_gain": MIN_RECOURSE_GAIN,
    "pmf_neighbors": NEIGHBORS,
    "pmf_prior_strength": PRIOR_STRENGTH,
}


def _stable_seed(season: str, gw: int, base_seed: int) -> int:
    raw = f"{season}|{int(gw)}|{int(base_seed)}|{EXPERIMENT_ID}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big") % (2 ** 32)


def _scenario_matrices(state: State, *, count: int, seed: int) -> list[dict]:
    """Latin hypercube de residuales discretos con media muestral exactamente cero."""
    if count < 2:
        raise ValueError("recourse requiere al menos dos escenarios")
    payload = state.horizon_pmf or {}
    if payload.get("support") != SUPPORT.tolist():
        raise ValueError("soporte PMF incompatible")
    rows = payload.get("rows") or {}
    matrices = [
        {int(gw): {int(element): float(value) for element, value in values.items()}
         for gw, values in state.horizon_xp.items()}
        for _ in range(count)
    ]
    rng = np.random.default_rng(seed)
    g0 = int(state.gw)
    for gw, mean_row in state.horizon_xp.items():
        probability_row = rows.get(int(gw), rows.get(str(gw), {}))
        discount = float(payload.get("decay", 0.84)) ** (int(gw) - g0)
        for element, mean in mean_row.items():
            probabilities = probability_row.get(int(element), probability_row.get(str(element)))
            if probabilities is None:
                continue
            probabilities = np.asarray(probabilities, dtype=float)
            if (probabilities.shape != SUPPORT.shape or (probabilities < 0).any()
                    or not np.isclose(probabilities.sum(), 1.0)):
                raise ValueError(f"PMF inválida para gw={gw}, element={element}")
            uniforms = (np.arange(count, dtype=float) + rng.random(count)) / count
            rng.shuffle(uniforms)
            draws = SUPPORT[np.searchsorted(np.cumsum(probabilities), uniforms)].astype(float)
            residuals = draws - draws.mean()
            for index, residual in enumerate(residuals):
                matrices[index][int(gw)][int(element)] = float(mean) + residual * discount
    return matrices


def _stage(solution, gw: int, *, squad_only: bool = False) -> FirstStage:
    return FirstStage(
        squad=tuple(solution.squad[gw]),
        starters=() if squad_only else tuple(solution.starters[gw]),
        captain=None if squad_only else int(solution.captain[gw]),
    )


def _decision_from_solution(state: State, solution, xp: dict, notes: list[str]) -> Decision:
    gw = int(state.gw)
    row = xp[gw]
    attributes = {candidate.element: candidate for candidate in state.candidates}
    for player in (state.squad.players if state.squad else ()):
        attributes.setdefault(
            player.element,
            Candidate(
                element=player.element, position=player.position, team=player.team,
                price=player.price, xp=0.0,
            ),
        )
    starters = sorted(solution.starters[gw], key=lambda element: -row.get(element, 0.0))
    captain = int(solution.captain[gw])
    vice = next(element for element in starters if element != captain)
    in_xi = set(starters)
    bench_gk = [
        element for element in solution.squad[gw]
        if element not in in_xi and attributes[element].position is Position.GKP
    ]
    bench_outfield = sorted(
        (element for element in solution.squad[gw]
         if element not in in_xi and attributes[element].position is not Position.GKP),
        key=lambda element: -row.get(element, 0.0),
    )
    cost = to_millions(sum(to_tenths(attributes[e].price) for e in solution.squad[gw]))
    expected = (
        sum(row.get(element, 0.0) for element in starters)
        + row.get(captain, 0.0)
        - state.rules["hit_cost"] * solution.hits[gw]
    )
    return Decision(
        season=state.season, gw=gw, squad_15=tuple(solution.squad[gw]),
        starters=tuple(starters), captain=captain, vice_captain=vice,
        bench_order=tuple(bench_gk + bench_outfield),
        transfers_in=() if state.squad is None else tuple(sorted(solution.buys[gw])),
        transfers_out=() if state.squad is None else tuple(sorted(solution.sells[gw])),
        hits=int(solution.hits[gw]), chip=solution.chips.get(gw),
        expected_points=round(expected, 2), total_cost=cost,
        bank_after=to_millions(solution.bank[gw]), policy=POLICY_NAME,
        notes=tuple(notes),
    )


def stochastic_recourse_policy(state: State, config) -> Decision:
    """Sample-average recourse neutral al riesgo; conserva exactamente la media."""
    xp = state.horizon_xp or {state.gw: {
        candidate.element: candidate.xp for candidate in state.candidates
    }}
    if len(xp) < 2 or not state.horizon_pmf:
        return replace(decide(state.gw, state, replace(config, policy="milp")),
                       policy=POLICY_NAME,
                       notes=("fallback determinista: sin horizonte/PMF para recourse",))

    decision_ocfg = optimizer_config(config, len(xp))
    evaluation_ocfg = replace(decision_ocfg, tie_break=0.0)
    mean_solution = solve(state, xp, decision_ocfg)
    scenarios = _scenario_matrices(
        state, count=SCENARIO_COUNT,
        seed=_stable_seed(state.season, state.gw, config.seed),
    )
    scenario_solutions = [solve(state, matrix, decision_ocfg) for matrix in scenarios]
    frequency = Counter(
        tuple(sorted(solution.squad[state.gw])) for solution in scenario_solutions
    )
    mean_key = tuple(sorted(mean_solution.squad[state.gw]))
    ordered = [mean_key]
    ordered.extend(
        key for key, _ in sorted(frequency.items(), key=lambda item: (-item[1], item[0]))
        if key != mean_key
    )
    ordered = ordered[:MAX_FIRST_STAGE_CANDIDATES]

    evaluated = []
    for squad in ordered:
        mean_fixed = (
            mean_solution if squad == mean_key else
            solve(
                state, xp, decision_ocfg,
                first_stage=FirstStage(squad=tuple(squad)),
            )
        )
        fixed = _stage(mean_fixed, state.gw)
        values = [
            solve(state, matrix, evaluation_ocfg, first_stage=fixed).objective
            for matrix in scenarios
        ]
        evaluated.append({
            "squad": squad,
            "solution": mean_fixed,
            "mean_recourse_objective": float(np.mean(values)),
            "scenario_sd": float(np.std(values, ddof=0)),
            "frequency": int(frequency.get(tuple(squad), 0)),
        })
    selected = max(
        evaluated,
        key=lambda row: (
            round(row["mean_recourse_objective"], 10),
            row["squad"] == mean_key,
            tuple(-element for element in row["squad"]),
        ),
    )
    mean_stage = next(row for row in evaluated if row["squad"] == mean_key)
    raw_gain = selected["mean_recourse_objective"] - mean_stage["mean_recourse_objective"]
    applied = raw_gain >= MIN_RECOURSE_GAIN
    if not applied:
        selected = mean_stage
    gain = raw_gain if applied else 0.0
    notes = [
        f"recourse discreto: {SCENARIO_COUNT} escenarios, "
        f"{len(evaluated)} primeras plantillas",
        f"ganancia SAA bruta vs primera etapa determinista: {raw_gain:+.6f}",
        f"recourse aplicado: {'si' if applied else 'no'}; ganancia usada {gain:+.3f}",
        f"umbral de estabilidad numérica: {MIN_RECOURSE_GAIN:.2f}",
        "media por jugador preservada exactamente; solo GW futuras reciben recourse",
    ]
    return _decision_from_solution(state, selected["solution"], xp, notes)


POLICIES[POLICY_NAME] = stochastic_recourse_policy


class DiscreteFixtureProjector:
    """Proyección h3 con PMFs causales entrenadas solo en temporadas previas."""

    def __init__(self, calibration: pd.DataFrame):
        self.calibration = calibration.reset_index(drop=True)
        self.snapshots: dict[tuple[str, int], pd.DataFrame] = {}

    def __call__(self, *, history, roster, models, season, gw, store, config,
                 max_gw, alias) -> ProjectionBundle:
        if alias:
            raise ValueError("DiscreteFixtureProjector requiere mode='named'")
        until = min(int(max_gw), int(gw) + int(config.horizon) - 1)
        current = roster.drop_duplicates("element", keep="first").copy()
        projection = fixture_horizon_projection(
            history=history, roster=current, modelos=models, season=season, gw=gw,
            horizon=until - int(gw) + 1,
            schedule=store.team_fixtures(season, gw, until), decay=config.decay,
        )
        self.snapshots[(season, int(gw))] = projection.current_detail
        pmf_rows = {}
        for target_gw, detail in projection.horizon_detail.items():
            probabilities = knn_discrete_pmf(
                self.calibration, detail, neighbors=NEIGHBORS,
                prior_strength=PRIOR_STRENGTH,
            )
            pmf_rows[int(target_gw)] = {
                int(element): probabilities[index].tolist()
                for index, element in enumerate(detail["element"].to_numpy(dtype=int))
            }
        current_xp = current["element"].map(
            projection.horizon_xp.get(int(gw), {})
        ).fillna(0.0)
        return ProjectionBundle(
            xp=pd.Series(current_xp.to_numpy(dtype=float), dtype=float),
            horizon_xp=projection.horizon_xp,
            horizon_sd=projection.horizon_sd,
            horizon_pmf={
                "schema": "mova-discrete-horizon-pmf-v1",
                "support": SUPPORT.tolist(),
                "rows": pmf_rows,
                "decay": float(config.decay),
                "mean_preserved_by_scenarios": True,
            },
        )


def _prediction_paths(args) -> dict[str, Path]:
    policy_parent = Path(args.policy_parent).resolve()
    parent_2020 = Path(args.parent_2020).resolve()
    paths = {
        "2020-21": parent_2020 / "replays/2020-21-season_fixture_h3-predictions.csv.gz",
        **{
            season: policy_parent / "replays" / f"{season}-season_fixture_h3-predictions.csv.gz"
            for season in ("2021-22", "2023-24", "2024-25", "2025-26")
        },
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"faltan predicciones causales: {missing}")
    return paths


def _incumbent_paths(args) -> dict[str, Path]:
    parent = Path(args.policy_parent).resolve()
    paths = {
        season: parent / "replays" / f"{season}-season_fixture_h3.json"
        for season in DEVELOPMENT_SEASONS + (EXTERNAL_SEASON,)
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"faltan replays incumbent: {missing}")
    return paths


def freeze_manifest(args, output: Path) -> dict:
    root = Path(__file__).resolve().parents[2]
    db = Path(args.fpl_db).resolve()
    predictions = _prediction_paths(args)
    incumbents = _incumbent_paths(args)
    payload = {
        "experiment_id": EXPERIMENT_ID,
        "parent_experiment_ids": [
            PARENT_POLICY_EXPERIMENT, PARENT_UNCERTAINTY_EXPERIMENT,
        ],
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_sha": _git_sha(root),
        "source_sha256": _source_sha(root),
        "model_source_sha256": _model_source_sha(root),
        "branch": subprocess.run(
            ["git", "branch", "--show-current"], cwd=root, check=True,
            capture_output=True, text=True,
        ).stdout.strip(),
        "dataset": {"path": str(db), "bytes": db.stat().st_size, "sha256": _sha256(db)},
        "prediction_inputs": {
            season: {"path": str(path), "sha256": _sha256(path), "bytes": path.stat().st_size}
            for season, path in predictions.items()
        },
        "incumbent_inputs": {
            season: {"path": str(path), "sha256": _sha256(path), "bytes": path.stat().st_size}
            for season, path in incumbents.items()
        },
        "development_seasons": list(DEVELOPMENT_SEASONS),
        "external_evaluation_season": EXTERNAL_SEASON,
        "calibration_rule": "strictly earlier closed seasons for every target",
        "incumbent": "season_fixture_h3",
        "challenger": RECOURSE_SPEC,
        "minimum_recourse_gain": MIN_RECOURSE_GAIN,
        "scenario_method": (
            "six Latin-hypercube discrete residual scenarios, sample-centered per "
            "player/GW to preserve the frozen xP mean exactly"
        ),
        "recourse": (
            "fix current squad/XI/captain, then re-optimize GW+1/GW+2 separately "
            "inside each scenario"
        ),
        "selection_gate": "positive mean PVA and wins in at least 2/3 development seasons",
        "north_star": "incremental PVA-38 versus already selected season_fixture_h3",
        "promotion": "forbidden; external evaluation and live shadow required",
        "known_limitations": [
            "perfect-information recourse is optimistic but applied symmetrically to first actions",
            "player and gameweek PMF residuals are sampled independently",
            "candidate action search is capped at three squads proposed by six scenarios",
            "2025-26 was previously observed and is a mechanical external evaluation only",
            "chips remain outside both policies",
            "one of 101,780 calibration outcomes is -7 and is censored to support floor -6",
        ],
    }
    destination = output / "manifest.json"
    if destination.exists():
        existing = json.loads(destination.read_text(encoding="utf-8"))
        def normalize(item):
            return {key: value for key, value in item.items() if key != "created_at"}

        if normalize(existing) != normalize(payload):
            raise RuntimeError("EXP-MOVA-2026-009 ya existe bajo otros inputs o código")
        return existing
    _write_json(destination, payload)
    return payload


def _load_predictions(manifest: dict, season: str) -> pd.DataFrame:
    spec = manifest["prediction_inputs"][season]
    path = Path(spec["path"])
    if _sha256(path) != spec["sha256"]:
        raise RuntimeError(f"predicciones alteradas: {season}")
    frame = pd.read_csv(path)
    required = {"position", "xp", "xp_sd", "n_fixtures", "actual"}
    if not required <= set(frame):
        raise ValueError(f"predicciones incompletas: {season}")
    actual = pd.to_numeric(frame["actual"], errors="raise")
    frame["actual_raw"] = actual
    frame["actual"] = actual.clip(lower=int(SUPPORT[0]), upper=int(SUPPORT[-1]))
    return frame


def _calibration(manifest: dict, target: str) -> pd.DataFrame:
    seasons = [season for season in CALIBRATION_SEASONS if season < target]
    if not seasons:
        raise RuntimeError(f"sin temporada de calibración previa a {target}")
    return pd.concat(
        [_load_predictions(manifest, season) for season in seasons],
        ignore_index=True,
    )


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


def summarize(records: list[dict], output: Path, manifest: dict, *, external=False) -> dict:
    totals = pd.DataFrame([
        {"season": record["season"], "variant": record["variant"],
         "points": int(record["points"])}
        for record in records
    ])
    pivot = totals.pivot(index="season", columns="variant", values="points")
    deltas = (pivot[POLICY_NAME] - pivot["season_fixture_h3"]).astype(int)
    incumbent = pd.concat([
        _gameweeks(record) for record in records
        if record["variant"] == "season_fixture_h3"
    ], ignore_index=True)
    challenger = pd.concat([
        _gameweeks(record) for record in records if record["variant"] == POLICY_NAME
    ], ignore_index=True)
    bootstrap = paired_policy_bootstrap(incumbent, challenger)
    wins = int((deltas > 0).sum())
    accepted = bool(float(deltas.mean()) > 0 and wins >= (1 if external else 2))
    payload = {
        "experiment_id": manifest["experiment_id"],
        "source_sha256": manifest["source_sha256"],
        "dataset_sha256": manifest["dataset"]["sha256"],
        "external_evaluation": bool(external),
        "totals": totals.to_dict("records"),
        "delta_by_season": {str(key): int(value) for key, value in deltas.items()},
        "mean_delta": float(deltas.mean()),
        "wins": wins,
        "paired_bootstrap": bootstrap,
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
            args, store, output, manifest, season, POLICY_NAME, RECOURSE_SPEC,
            INHERITED_EVENT_WEIGHT,
            projector=DiscreteFixtureProjector(_calibration(manifest, season)),
        ))
    return summarize(records, output, manifest)


def external_evaluation(args, store: CachedStore, output: Path, manifest: dict) -> dict:
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
            RECOURSE_SPEC, INHERITED_EVENT_WEIGHT,
            projector=DiscreteFixtureProjector(_calibration(manifest, EXTERNAL_SEASON)),
        ),
    ]
    return summarize(records, output, manifest, external=True)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("manifest", "select", "external-evaluation"))
    parser.add_argument("--fpl-db", required=True)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--policy-parent", default=str(DEFAULT_POLICY_PARENT))
    parser.add_argument("--parent-2020", default=str(DEFAULT_2020_PARENT))
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
        result = (
            select(args, store, output, manifest)
            if args.phase == "select"
            else external_evaluation(args, store, output, manifest)
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
