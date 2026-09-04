#!/usr/bin/env python3
"""Estado causal de inicio de temporada para el modelo de minutos.

El runtime vivo heredado mantiene congelado el cierre de la temporada anterior
durante toda la temporada nueva. Este laboratorio aísla ese defecto y compara
tratamientos causales del cambio de régimen antes de modificar producción.

Fases:

``manifest``
    Congela código, dataset, modelos, variantes y gates antes de ver resultados.
``select``
    Selecciona estado con tres temporadas de desarrollo usando proper scores.
``decision-development``
    Exige que la mejora predictiva llegue a puntos reales de la política h3.
``external``
    Abre 2025-26 una sola vez y evalúa predicción y decisión conjuntamente.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from experiments.long_horizon.metrics import paired_policy_bootstrap
from experiments.long_horizon.projection import FixtureProjector
from experiments.long_horizon.run import (
    CachedStore,
    _git_sha,
    _sha256,
    _source_sha,
    _write_json,
)
from mova_fpl.engine.runner import Config
from mova_fpl.engine.simulator import replay
from mova_fpl.models.features.minutes_features import build_targets
from mova_fpl.models.minutes import brier, expected_calibration_error
from mova_fpl.trace import TraceWriter


EXPERIMENT_ID = "EXP-MOVA-2026-013"
PARENT_EXPERIMENT_ID = "EXP-MOVA-2026-003"
DEVELOPMENT_SEASONS = ("2021-22", "2023-24", "2024-25")
EXTERNAL_SEASON = "2025-26"
EVALUATION_GWS = tuple(range(2, 9))
VARIANTS = (
    "stale_previous",
    "current_reset",
    "current_fallback",
    "append_tail4",
    "append_full",
)
CANDIDATES = tuple(name for name in VARIANTS if name != "stale_previous")
SIMPLICITY_ORDER = {name: index for index, name in enumerate((
    "current_reset", "current_fallback", "append_tail4", "append_full",
))}
DEFAULT_EXPERIMENTS = Path(__file__).resolve().parents[3] / "mova-fpl-experiments"
DEFAULT_OUTPUT = DEFAULT_EXPERIMENTS / EXPERIMENT_ID
DEFAULT_PARENT = DEFAULT_EXPERIMENTS / PARENT_EXPERIMENT_ID


def _previous_season(store: CachedStore, season: str) -> str:
    seasons = store.seasons()
    try:
        index = seasons.index(season)
    except ValueError as exc:
        raise ValueError(f"temporada ausente del dataset: {season}") from exc
    if index == 0:
        raise ValueError(f"{season} no tiene temporada anterior en el dataset")
    return str(seasons[index - 1])


def boundary_history(store: CachedStore, season: str, gw: int, variant: str,
                     *, target_keys: set[str] | None = None) -> pd.DataFrame:
    """Construye el information set de una variante sin leer GW objetivo/futuro.

    GW1 conserva el cierre anterior para todas las variantes. Desde GW2, el
    challenger puede tratar la nueva temporada como un cambio de régimen. El
    fallback añade pasado únicamente para jugadores del catálogo objetivo que
    todavía no tienen ni una fila en la temporada actual.
    """
    if variant not in VARIANTS:
        raise ValueError(f"variante desconocida: {variant}")
    previous = _previous_season(store, season)
    prior = CachedStore.as_of(store, previous, 1_000)
    current = CachedStore.as_of(store, season, int(gw))
    if current.empty or variant == "stale_previous":
        return prior.copy()
    if variant == "current_reset":
        return current.copy()
    if variant == "current_fallback":
        current_keys = set(current["player_key"].dropna().astype(str))
        requested = target_keys or set()
        missing = requested - current_keys
        fallback = prior[prior["player_key"].astype(str).isin(missing)]
        return pd.concat([fallback, current], ignore_index=True)
    if variant == "append_tail4":
        last = int(pd.to_numeric(prior["gw"], errors="coerce").max())
        prior = prior[pd.to_numeric(prior["gw"], errors="coerce") > last - 4]
    return pd.concat([prior, current], ignore_index=True)


class BoundaryStore(CachedStore):
    """Store experimental que cambia solamente el estado entregado al proyector."""

    def __init__(self, db_path: str | Path, variant: str):
        super().__init__(db_path)
        if variant not in VARIANTS:
            raise ValueError(f"variante desconocida: {variant}")
        self.variant = variant

    def as_of(self, season: str, gw: int, columns=None) -> pd.DataFrame:
        if columns is not None:
            raise ValueError("BoundaryStore experimental exige el frame causal completo")
        target_keys = set(
            super().roster(season, gw)["player_key"].dropna().astype(str)
        )
        return boundary_history(
            self, season, gw, self.variant, target_keys=target_keys,
        )


def _file_spec(path: Path) -> dict:
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    return {
        "path": str(resolved),
        "bytes": resolved.stat().st_size,
        "sha256": _sha256(resolved),
    }


def _model_paths(parent: Path) -> dict[str, Path]:
    return {
        season: parent / "artifacts" / f"fold-{season}.joblib"
        for season in (*DEVELOPMENT_SEASONS, EXTERNAL_SEASON)
    }


def freeze_manifest(args, output: Path) -> dict:
    root = Path(__file__).resolve().parents[2]
    db = Path(args.fpl_db).resolve()
    parent = Path(args.parent_output).resolve()
    parent_manifest = parent / "manifest.json"
    paths = _model_paths(parent)
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
        "runtime_versions": {
            package: importlib.metadata.version(package)
            for package in ("numpy", "pandas", "scikit-learn", "scipy", "joblib")
        },
        "dataset": _file_spec(db),
        "parent_manifest": _file_spec(parent_manifest),
        "fold_models": {
            season: _file_spec(path) for season, path in paths.items()
        },
        "development_seasons": list(DEVELOPMENT_SEASONS),
        "external_evaluation_season": EXTERNAL_SEASON,
        "evaluation_gws": list(EVALUATION_GWS),
        "variants": {
            "stale_previous": "previous season GW1-end; exact inherited live defect",
            "current_reset": "current-season closed GWs; previous season only at GW1",
            "current_fallback": (
                "current-season closed GWs plus previous history only for target players "
                "with no current-season row"
            ),
            "append_tail4": "last four previous-season GWs plus current-season closed GWs",
            "append_full": "full previous season plus current-season closed GWs",
        },
        "primary_metric": "mean three-class minutes log loss over GW2-GW8",
        "guardrails": [
            "three-class Brier",
            "p60 Brier and ECE",
            "p0 Brier and ECE",
            "cold-start and previous-zero/current-starter slices",
            "PVA-38 under the frozen season_fixture_h3 policy",
        ],
        "selection_gate": (
            "lowest mean development log loss among candidates improving stale_previous "
            "in every development season and not worsening mean p60 Brier"
        ),
        "decision_development_gate": (
            "positive mean PVA-38 and wins in at least two of three development seasons"
        ),
        "external_gate": (
            "selected candidate improves both log loss and p60 Brier and scores positive "
            "PVA-38 on 2025-26"
        ),
        "policy": {
            "name": "season_fixture_h3",
            "horizon": 3,
            "decay": 0.84,
            "chips": "none",
        },
        "classification": "causal regime-boundary correction; no synthetic efficacy data",
        "promotion": "forbidden; live shadow plus explicit approval required",
        "known_limitations": [
            "2025-26 has been inspected in prior experiments and is not cognitively pristine",
            "historical fixture replay retains final postponement scheduling",
            "the experiment isolates inference state and does not retrain model parameters",
            "GW2-GW8 emphasizes the observed failure mode and is not a full-season forecast metric",
            "2022-23 is excluded from policy replay because its World Cup transfer reset is unmodeled",
        ],
        "research_basis": [
            "West, Harrison & Migon (1985), Dynamic Generalized Linear Models",
            "Owen (2011), Dynamic Bayesian forecasting models of football match outcomes",
            "Gneiting & Raftery (2007), Strictly Proper Scoring Rules",
            "Gibbs & Candes (2021), Adaptive Conformal Inference Under Distribution Shift",
            "Elmachtoub & Grigas (2022), Smart Predict-then-Optimize",
        ],
    }
    destination = output / "manifest.json"
    if destination.exists():
        existing = json.loads(destination.read_text(encoding="utf-8"))
        strip_time = lambda value: {  # noqa: E731
            key: item for key, item in value.items() if key != "created_at"
        }
        if strip_time(existing) != strip_time(payload):
            raise RuntimeError(
                f"{EXPERIMENT_ID} ya existe bajo otro código, dataset o modelos"
            )
        return existing
    _write_json(destination, payload)
    return payload


def _verify_input(spec: dict) -> Path:
    path = Path(spec["path"])
    if not path.is_file() or _sha256(path) != spec["sha256"]:
        raise RuntimeError(f"input ausente o alterado: {path}")
    return path


def _actual_classes(store: CachedStore, season: str, gw: int,
                    roster: pd.DataFrame) -> np.ndarray:
    actual = (CachedStore.results(store, season, gw)
              .groupby("element", as_index=True)["minutes"].sum())
    minutes = roster["element"].map(actual).fillna(0.0).to_numpy(dtype=float)
    return np.select([minutes <= 0, minutes < 60], [0, 1], default=2).astype(int)


def _prediction_rows(store: CachedStore, model, season: str,
                     variants: tuple[str, ...]) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for gw in EVALUATION_GWS:
        roster = CachedStore.roster(store, season, gw)
        if roster.empty:
            continue
        keys = set(roster["player_key"].dropna().astype(str))
        current = CachedStore.as_of(store, season, gw)
        previous = CachedStore.as_of(
            store, _previous_season(store, season), 1_000,
        )
        y = _actual_classes(store, season, gw, roster)
        n_current = current.groupby("player_key").size()
        previous_last = (previous.sort_values(["player_key", "gw", "fixture"])
                         .groupby("player_key")["minutes"].last())
        for variant in variants:
            history = boundary_history(
                store, season, gw, variant, target_keys=keys,
            )
            built = build_targets(history, roster)
            probability = model.predict_proba_built(built)
            frame = pd.DataFrame({
                "season": season,
                "gw": int(gw),
                "variant": variant,
                "element": roster["element"].to_numpy(dtype=int),
                "player_key": roster["player_key"].astype(str).to_numpy(),
                "position": roster["position"].astype(str).to_numpy(),
                "actual_class": y,
                "p0": probability[:, 0],
                "p1": probability[:, 1],
                "p60": probability[:, 2],
                "n_current": roster["player_key"].map(n_current).fillna(0).to_numpy(int),
                "previous_last_minutes": roster["player_key"].map(previous_last).to_numpy(float),
            })
            frame["cold_current"] = frame["n_current"] == 0
            frame["previous_zero_current_starter"] = (
                frame["previous_last_minutes"].fillna(-1).eq(0)
                & frame["actual_class"].eq(2)
            )
            rows.append(frame)
    if not rows:
        raise RuntimeError(f"sin filas predictivas para {season}")
    return pd.concat(rows, ignore_index=True)


def predictive_metrics(frame: pd.DataFrame) -> dict:
    if frame.empty:
        return {"n": 0}
    y = frame["actual_class"].to_numpy(dtype=int)
    probability = frame[["p0", "p1", "p60"]].to_numpy(dtype=float)
    one_hot = np.eye(3, dtype=float)[y]
    y0 = (y == 0).astype(float)
    y60 = (y == 2).astype(float)
    return {
        "n": int(len(frame)),
        "log_loss_3c": float(-np.mean(np.log(np.clip(
            probability[np.arange(len(y)), y], 1e-12, 1.0,
        )))),
        "brier_3c": float(np.mean(np.sum((probability - one_hot) ** 2, axis=1))),
        "brier_p60": brier(y60, probability[:, 2]),
        "ece_p60": expected_calibration_error(y60, probability[:, 2]),
        "brier_p0": brier(y0, probability[:, 0]),
        "ece_p0": expected_calibration_error(y0, probability[:, 0]),
    }


def _metric_table(rows: pd.DataFrame) -> pd.DataFrame:
    records = []
    for (season, variant), frame in rows.groupby(["season", "variant"], sort=True):
        record = {"season": season, "variant": variant, **predictive_metrics(frame)}
        for column in ("cold_current", "previous_zero_current_starter"):
            sliced = predictive_metrics(frame[frame[column]])
            for key, value in sliced.items():
                record[f"{column}_{key}"] = value
        records.append(record)
    return pd.DataFrame(records)


def select_predictive(args, output: Path, manifest: dict) -> dict:
    store = CachedStore(args.fpl_db)
    rows = []
    for season in DEVELOPMENT_SEASONS:
        model_path = _verify_input(manifest["fold_models"][season])
        bundle = joblib.load(model_path)
        rows.append(_prediction_rows(store, bundle["minutes"], season, VARIANTS))
    predictions = pd.concat(rows, ignore_index=True)
    metrics = _metric_table(predictions)
    pivot_log = metrics.pivot(index="season", columns="variant", values="log_loss_3c")
    means = metrics.groupby("variant", as_index=True).mean(numeric_only=True)
    eligible = []
    for candidate in CANDIDATES:
        improves_every_season = bool(
            (pivot_log[candidate] < pivot_log["stale_previous"]).all()
        )
        p60_not_worse = bool(
            means.loc[candidate, "brier_p60"] <= means.loc["stale_previous", "brier_p60"]
        )
        if improves_every_season and p60_not_worse:
            eligible.append(candidate)
    selected = min(
        eligible,
        key=lambda name: (means.loc[name, "log_loss_3c"], SIMPLICITY_ORDER[name]),
    ) if eligible else "stale_previous"
    payload = {
        "experiment_id": manifest["experiment_id"],
        "source_sha256": manifest["source_sha256"],
        "dataset_sha256": manifest["dataset"]["sha256"],
        "selected_variant": selected,
        "candidate_accepted": selected != "stale_previous",
        "eligible_candidates": eligible,
        "selection_gate": manifest["selection_gate"],
        "mean_metrics": {
            str(index): {
                str(key): float(value) for key, value in row.items()
                if np.isfinite(value)
            }
            for index, row in means.iterrows()
        },
        "season_metrics": metrics.to_dict("records"),
        "promotion": "not_authorized",
    }
    predictions.to_csv(output / "development-predictions.csv.gz", index=False,
                       compression="gzip")
    metrics.to_csv(output / "development-predictive-metrics.csv", index=False)
    _write_json(output / "selection.json", payload)
    return payload


def _load_selection(output: Path, manifest: dict) -> dict:
    path = output / "selection.json"
    if not path.is_file():
        raise FileNotFoundError("falta selection.json; ejecute select")
    selection = json.loads(path.read_text(encoding="utf-8"))
    if (selection.get("source_sha256") != manifest["source_sha256"]
            or selection.get("dataset_sha256") != manifest["dataset"]["sha256"]):
        raise RuntimeError("selection.json no pertenece al manifest vigente")
    if not selection.get("candidate_accepted"):
        raise RuntimeError("ningún tratamiento de estado superó el gate predictivo")
    return selection


def _run_policy(args, output: Path, manifest: dict, season: str,
                variant: str) -> dict:
    destination = output / "replays" / f"{season}-{variant}.json"
    if destination.exists() and not args.force_replays:
        cached = json.loads(destination.read_text(encoding="utf-8"))
        if (cached.get("source_sha256") == manifest["source_sha256"]
                and cached.get("dataset_sha256") == manifest["dataset"]["sha256"]
                and cached.get("model_sha256") == manifest["fold_models"][season]["sha256"]):
            return cached
        raise RuntimeError(f"replay incompatible ya existe: {destination}")
    model_path = _verify_input(manifest["fold_models"][season])
    bundle = joblib.load(model_path)
    store = BoundaryStore(args.fpl_db, variant)
    config = Config(
        policy="milp", projector="points", model_version=f"fold-{season}",
        horizon=3, decay=0.84, top_k=args.top_k, time_limit=args.time_limit,
        chip_policy="none",
    )
    trace_path = output / "traces" / f"{season}-{variant}.db"
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    report = replay(
        season, "named", config, store=store, trace=TraceWriter(trace_path),
        run_id=f"{EXPERIMENT_ID}-{season}-{variant}", max_gw=38, verbose=False,
        history_mode="season", model_bundle=bundle,
        projection_fn=FixtureProjector(),
    )
    payload = {
        "experiment_id": manifest["experiment_id"],
        "source_sha256": manifest["source_sha256"],
        "dataset_sha256": manifest["dataset"]["sha256"],
        "model_sha256": manifest["fold_models"][season]["sha256"],
        "season": season,
        "variant": variant,
        "config": asdict(config),
        "points": int(report.total),
        "gameweeks": report.gameweeks,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    report.to_frame().to_csv(
        output / "replays" / f"{season}-{variant}.csv", index=False,
    )
    _write_json(destination, payload)
    print(f"replay {season} {variant}: {report.total} pts", flush=True)
    return payload


def _decision_summary(records: list[dict], manifest: dict) -> dict:
    totals = pd.DataFrame([
        {"season": record["season"], "variant": record["variant"],
         "points": int(record["points"])}
        for record in records
    ])
    candidate = next(name for name in totals["variant"].unique()
                     if name != "stale_previous")
    pivot = totals.pivot(index="season", columns="variant", values="points")
    deltas = pivot[candidate] - pivot["stale_previous"]
    baseline = pd.concat([
        pd.DataFrame(record["gameweeks"])[["gw", "points"]].assign(
            season=record["season"],
        )
        for record in records if record["variant"] == "stale_previous"
    ], ignore_index=True)
    challenger = pd.concat([
        pd.DataFrame(record["gameweeks"])[["gw", "points"]].assign(
            season=record["season"],
        )
        for record in records if record["variant"] == candidate
    ], ignore_index=True)
    return {
        "candidate": candidate,
        "totals": totals.to_dict("records"),
        "delta_by_season": {str(key): int(value) for key, value in deltas.items()},
        "wins": int((deltas > 0).sum()),
        "losses": int((deltas < 0).sum()),
        "mean_delta": float(deltas.mean()),
        "paired_bootstrap": paired_policy_bootstrap(
            baseline, challenger, draws=50_000, block_size=4, seed=42,
        ),
    }


def decision_development(args, output: Path, manifest: dict) -> dict:
    selection = _load_selection(output, manifest)
    candidate = selection["selected_variant"]
    records = [
        _run_policy(args, output, manifest, season, variant)
        for season in DEVELOPMENT_SEASONS
        for variant in ("stale_previous", candidate)
    ]
    summary = _decision_summary(records, manifest)
    summary |= {
        "experiment_id": manifest["experiment_id"],
        "source_sha256": manifest["source_sha256"],
        "dataset_sha256": manifest["dataset"]["sha256"],
        "gate": manifest["decision_development_gate"],
        "candidate_accepted": bool(summary["mean_delta"] > 0 and summary["wins"] >= 2),
        "promotion": "not_authorized",
    }
    _write_json(output / "decision-development.json", summary)
    return summary


def _load_decision_gate(output: Path, manifest: dict) -> dict:
    path = output / "decision-development.json"
    if not path.is_file():
        raise FileNotFoundError("falta decision-development.json")
    result = json.loads(path.read_text(encoding="utf-8"))
    if (result.get("source_sha256") != manifest["source_sha256"]
            or result.get("dataset_sha256") != manifest["dataset"]["sha256"]):
        raise RuntimeError("gate decisional no pertenece al manifest vigente")
    if not result.get("candidate_accepted"):
        raise RuntimeError("el challenger predictivo no superó el gate decisional")
    return result


def external_evaluation(args, output: Path, manifest: dict) -> dict:
    destination = output / "external-evaluation.json"
    selection = _load_selection(output, manifest)
    _load_decision_gate(output, manifest)
    candidate = str(selection["selected_variant"])
    if destination.exists():
        sealed = json.loads(destination.read_text(encoding="utf-8"))
        if (sealed.get("source_sha256") == manifest["source_sha256"]
                and sealed.get("dataset_sha256") == manifest["dataset"]["sha256"]
                and sealed.get("candidate") == candidate):
            return sealed
        raise RuntimeError("evaluación externa ya abierta bajo otro código o candidato")

    store = CachedStore(args.fpl_db)
    model_path = _verify_input(manifest["fold_models"][EXTERNAL_SEASON])
    bundle = joblib.load(model_path)
    predictions = _prediction_rows(
        store, bundle["minutes"], EXTERNAL_SEASON,
        ("stale_previous", candidate),
    )
    metrics = _metric_table(predictions)
    by_variant = metrics.set_index("variant")
    decision_records = [
        _run_policy(args, output, manifest, EXTERNAL_SEASON, variant)
        for variant in ("stale_previous", candidate)
    ]
    decision = _decision_summary(decision_records, manifest)
    log_delta = float(
        by_variant.loc[candidate, "log_loss_3c"]
        - by_variant.loc["stale_previous", "log_loss_3c"]
    )
    p60_delta = float(
        by_variant.loc[candidate, "brier_p60"]
        - by_variant.loc["stale_previous", "brier_p60"]
    )
    pva = int(decision["delta_by_season"][EXTERNAL_SEASON])
    accepted = bool(log_delta < 0 and p60_delta < 0 and pva > 0)
    predictions.to_csv(output / "external-predictions.csv.gz", index=False,
                       compression="gzip")
    metrics.to_csv(output / "external-predictive-metrics.csv", index=False)
    payload = {
        "experiment_id": manifest["experiment_id"],
        "source_sha256": manifest["source_sha256"],
        "dataset_sha256": manifest["dataset"]["sha256"],
        "external_opened_once": True,
        "season": EXTERNAL_SEASON,
        "candidate": candidate,
        "predictive_metrics": metrics.to_dict("records"),
        "log_loss_delta_vs_stale": log_delta,
        "p60_brier_delta_vs_stale": p60_delta,
        "decision": decision,
        "pva_38": pva,
        "external_gate": manifest["external_gate"],
        "candidate_accepted": accepted,
        "promotion": "not_authorized; live shadow and approval required",
    }
    _write_json(destination, payload)
    return payload


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "phase",
        choices=("manifest", "select", "decision-development", "external"),
    )
    parser.add_argument("--fpl-db", required=True)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--parent-output", default=str(DEFAULT_PARENT))
    parser.add_argument("--top-k", type=int, default=30)
    parser.add_argument("--time-limit", type=int, default=30)
    parser.add_argument("--force-replays", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest = freeze_manifest(args, output)
    if args.phase == "manifest":
        result = manifest
    elif args.phase == "select":
        result = select_predictive(args, output, manifest)
    elif args.phase == "decision-development":
        result = decision_development(args, output, manifest)
    else:
        result = external_evaluation(args, output, manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
