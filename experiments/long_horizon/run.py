#!/usr/bin/env python3
"""Harness reproducible para seleccionar y evaluar la política long-horizon.

Fases deliberadamente separadas:

1. ``screen-events`` selecciona el único hiperparámetro del modelo de eventos
   en temporadas de desarrollo.
2. ``select-policy`` compara ablaciones completas, también en desarrollo.
3. ``holdout`` abre 2025-26 una sola vez con la configuración congelada.

Ninguna fase publica modelos ni cambia el runtime operativo.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import mean_poisson_deviance

from experiments.long_horizon.metrics import paired_policy_bootstrap, predictive_metrics
from experiments.long_horizon.models import fit_temporal_fold, with_event_proxy
from experiments.long_horizon.projection import FixtureProjector
from mova_fpl.data.store import Store, assert_causal
from mova_fpl.engine.runner import Config
from mova_fpl.engine.simulator import replay
from mova_fpl.trace import TraceWriter


EXPERIMENT_ID = "EXP-MOVA-2026-003"
PARENT_EXPERIMENT_ID = "EXP-MOVA-2026-002"
INHERITED_EVENT_WEIGHT = 0.45
DEFAULT_OUTPUT = (Path(__file__).resolve().parents[3] / "mova-fpl-experiments"
                  / EXPERIMENT_ID)
SELECTION_SEASONS = ("2021-22", "2023-24", "2024-25")
HOLDOUT_SEASON = "2025-26"
EVENT_WEIGHTS = (0.0, 0.15, 0.30, 0.45, 0.60, 0.75, 0.90)
RECENCY_HALF_LIVES = (8.0, 16.0, 32.0, 64.0, 96.0, 128.0)


POLICY_VARIANTS = {
    # V2 conserva el estado season-only que ganó en EXP-001 y añade una variable
    # por escalón. Los parámetros de eventos vienen del screening del padre.
    "control_h3": {
        "history_mode": "season", "fixture": False, "horizon": 3, "decay": 0.84,
        "recency": False, "events": False, "transfer_penalty": 0.0,
        "uncertainty_transfer_weight": 0.0,
    },
    "season_fixture_h3": {
        "history_mode": "season", "fixture": True, "horizon": 3, "decay": 0.84,
        "recency": False, "events": False, "transfer_penalty": 0.0,
        "uncertainty_transfer_weight": 0.0,
    },
    "season_fixture_h6": {
        "history_mode": "season", "fixture": True, "horizon": 6, "decay": 0.84,
        "recency": False, "events": False, "transfer_penalty": 0.0,
        "uncertainty_transfer_weight": 0.0,
    },
    "season_fixture_h6_events": {
        "history_mode": "season", "fixture": True, "horizon": 6, "decay": 0.84,
        "recency": False, "events": True, "transfer_penalty": 0.0,
        "uncertainty_transfer_weight": 0.0,
    },
    "season_fixture_h6_events_stable": {
        "history_mode": "season", "fixture": True, "horizon": 6, "decay": 0.84,
        "recency": False, "events": True, "transfer_penalty": 0.35,
        "uncertainty_transfer_weight": 0.05,
    },
}


class CachedStore(Store):
    """Store de solo lectura con snapshots de temporada cacheados en memoria.

    El filtro causal se vuelve a aplicar en cada llamada. Solo evita convertir
    las mismas 200 mil filas desde SQLite 38 veces por fold.
    """

    def __init__(self, db_path):
        super().__init__(db_path)
        self._season_cache: dict[str, pd.DataFrame] = {}
        self._multi_cache: dict[str, pd.DataFrame] = {}

    @staticmethod
    def _columns(frame: pd.DataFrame, columns) -> pd.DataFrame:
        if columns is None:
            return frame
        requested = list(columns)
        for required in ("gw", "season"):
            if required not in requested:
                requested.append(required)
        return frame[requested]

    def as_of(self, season: str, gw: int, columns=None) -> pd.DataFrame:
        if season not in self._season_cache:
            self._season_cache[season] = super().as_of(season, 1_000)
        frame = self._season_cache[season]
        out = frame[frame["gw"] < int(gw)]
        out = self._columns(out, columns).copy()
        assert_causal(out, season, int(gw))
        return out

    def multi_season_as_of(self, season: str, gw: int, columns=None) -> pd.DataFrame:
        if season not in self._multi_cache:
            self._multi_cache[season] = super().multi_season_as_of(season, 1_000)
        frame = self._multi_cache[season]
        out = frame[(frame["season"] < season)
                    | ((frame["season"] == season) & (frame["gw"] < int(gw)))]
        out = self._columns(out, columns).copy()
        assert_causal(out[out["season"] == season], season, int(gw))
        return out


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_sha(root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def _source_sha(root: Path) -> str:
    """Hash del código efectivo, incluso antes de crear el commit experimental."""
    digest = hashlib.sha256()
    paths = list((root / "mova_fpl").rglob("*.py"))
    paths += list((root / "experiments" / "long_horizon").rglob("*.py"))
    for path in sorted(paths):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _model_source_sha(root: Path) -> str:
    """Hash mínimo que invalida artefactos entrenados, no el orquestador."""
    digest = hashlib.sha256()
    paths = list((root / "mova_fpl" / "models").rglob("*.py"))
    paths.append(root / "experiments" / "long_horizon" / "models.py")
    for path in sorted(paths):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def freeze_manifest(args, output: Path) -> dict:
    root = Path(__file__).resolve().parents[2]
    db = Path(args.fpl_db).resolve()
    manifest = {
        "experiment_id": EXPERIMENT_ID,
        "parent_experiment_id": PARENT_EXPERIMENT_ID,
        "inherited_hyperparameters": {
            "event_proxy_weight": INHERITED_EVENT_WEIGHT,
            "source_experiment": PARENT_EXPERIMENT_ID,
            "selection_rule": "minimum goals+assists Poisson deviance on development seasons",
        },
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_sha": _git_sha(root),
        "source_sha256": _source_sha(root),
        "model_source_sha256": _model_source_sha(root),
        "branch": subprocess.run(
            ["git", "branch", "--show-current"], cwd=root, check=True,
            capture_output=True, text=True,
        ).stdout.strip(),
        "dataset": {"path": str(db), "bytes": db.stat().st_size, "sha256": _sha256(db)},
        "selection_seasons": SELECTION_SEASONS,
        "sealed_holdout": HOLDOUT_SEASON,
        "event_weight_grid": EVENT_WEIGHTS,
        "recency_half_life_grid": RECENCY_HALF_LIVES,
        "policy_variants": POLICY_VARIANTS,
        "north_star": "PVA-38 paired season points vs control_h3",
        "forecast_guardrails": ["CRPS", "MAE", "Spearman", "50/80/90% coverage"],
        "promotion": "forbidden; requires socialization and explicit approval",
        "known_limitations": [
            "L-01 historical calendar contains final rescheduling knowledge",
            "Normal CRPS is an approximation to a zero-inflated discrete score distribution",
            "DGW fixture variances are conditionally summed; shared availability correlation pending",
            "Only four modern seasons have position/team coverage for full policy replay",
            "2022-23 excluded because the World Cup unlimited-transfer reset is not modeled",
            "2024-25 Assistant Manager assets are excluded; historical chips are outside replay scope",
        ],
    }
    _write_json(output / "manifest.json", manifest)
    return manifest


def load_fold(store: Store, season: str, output: Path, data_sha: str, model_source_sha: str,
              *, force=False) -> tuple[dict, pd.DataFrame]:
    path = output / "artifacts" / f"fold-{season}.joblib"
    train = store.multi_season_as_of(season, 1)
    if path.exists() and not force:
        bundle = joblib.load(path)
        metadata = bundle.get("metadata", {})
        if (metadata.get("dataset_sha256") == data_sha
                and metadata.get("model_source_sha256") == model_source_sha):
            return bundle, train
    bundle = fit_temporal_fold(train, season)
    bundle["metadata"]["dataset_sha256"] = data_sha
    bundle["metadata"]["model_source_sha256"] = model_source_sha
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".joblib.tmp")
    joblib.dump(bundle, temporary)
    temporary.replace(path)
    return bundle, train


def _event_rate_rows(store: Store, season: str, variants: dict[float, dict]) -> pd.DataFrame:
    """Scoring Poisson del único componente que cambia: goles/asistencias.

    Se usa el tiempo jugado real solo como *offset* de exposición al evaluar;
    nunca entra a la predicción ni a la política. Así todos los pesos comparten
    exactamente estado, rival y disponibilidad y el screening no reejecuta el
    resto del modelo cuatro veces.
    """
    from mova_fpl.models.features.points_features import normaliza_posicion, player_rates

    rows = []
    for gw in range(1, 39):
        history = store.multi_season_as_of(season, gw)
        roster = store.roster(season, gw)
        actual = store.results(season, gw)
        if roster.empty or actual.empty:
            continue
        positions = normaliza_posicion(roster["position"]).fillna("MID")
        truth = (actual.groupby("element", as_index=False)
                 .agg(actual_goals=("goals_scored", "sum"),
                      actual_assists=("assists", "sum"), minutes=("minutes", "sum")))
        target = roster[["element"]].merge(truth, on="element", how="left").fillna(0.0)
        exposure = target["minutes"].to_numpy(dtype=float) / 90.0
        played = exposure > 0
        state_cache = {}
        for variant_value, models in variants.items():
            points = models["points"]
            cache_key = points.player_recency_half_life
            if cache_key not in state_cache:
                prepared = points.prepare_history(history)
                rates = prepared["player_rates"]
                state_cache[cache_key] = points._estado_jugador(
                    roster, rates, prepared["priors"], positions)
            state = state_cache[cache_key]
            goals = points.goals
            rate_g = goals.rate(state, positions, "gol")
            rate_a = goals.rate(state, positions, "asistencia")
            for component, rate, actual_col in (
                    ("goals", rate_g, "actual_goals"),
                    ("assists", rate_a, "actual_assists")):
                part = pd.DataFrame({
                    "season": season, "gw": gw, "element": roster["element"].to_numpy(),
                    "variant_value": float(variant_value), "component": component,
                    "actual": target[actual_col].to_numpy(dtype=float),
                    "expected": np.clip(rate * exposure, 1e-6, None),
                    "minutes": target["minutes"].to_numpy(dtype=float),
                })
                rows.append(part[played])
    return pd.concat(rows, ignore_index=True)


def screen_events(args, store: Store, output: Path, manifest: dict) -> dict:
    result_rows, detail_rows = [], []
    for season in SELECTION_SEASONS:
        base, train = load_fold(store, season, output, manifest["dataset"]["sha256"],
                                manifest["model_source_sha256"],
                                force=args.force_models)
        variants = {weight: (base if weight == 0 else with_event_proxy(base, train, weight))
                    for weight in EVENT_WEIGHTS}
        detail = _event_rate_rows(store, season, variants)
        detail_rows.append(detail)
        for weight, group in detail.groupby("variant_value"):
            result_rows.append({
                "season": season, "event_weight": float(weight), "rows": int(len(group)),
                "poisson_deviance": float(mean_poisson_deviance(
                    group["actual"], group["expected"])),
                "mae_count": float(np.mean(np.abs(group["actual"] - group["expected"]))),
                "bias_count": float(np.mean(group["expected"] - group["actual"])),
            })
        print(f"screen {season}: {len(detail):,} player-component rows", flush=True)

    metrics = pd.DataFrame(result_rows)
    aggregate = (metrics.groupby("event_weight", as_index=False)
                 .agg({"rows": "sum", "poisson_deviance": "mean",
                       "mae_count": "mean", "bias_count": "mean"}))
    selected = float(aggregate.loc[aggregate["poisson_deviance"].idxmin(), "event_weight"])
    payload = {
        "experiment_id": EXPERIMENT_ID,
        "source_sha256": manifest["source_sha256"],
        "dataset_sha256": manifest["dataset"]["sha256"],
        "selection_only": True,
        "primary_metric": "mean season Poisson deviance of goals+assists (lower is better)",
        "selected_event_weight": selected,
        "by_season": metrics.to_dict("records"),
        "aggregate": aggregate.to_dict("records"),
    }
    _write_json(output / "event-screen.json", payload)
    metrics.to_csv(output / "event-screen-by-season.csv", index=False)
    aggregate.to_csv(output / "event-screen-aggregate.csv", index=False)
    pd.concat(detail_rows, ignore_index=True).to_csv(
        output / "event-screen-predictions.csv.gz", index=False, compression="gzip")
    return payload


def screen_recency(args, store: Store, output: Path, manifest: dict) -> dict:
    """Selecciona la vida media del estado antes de evaluar decisiones."""
    result_rows, detail_rows = [], []
    prediction_path = output / "recency-screen-predictions.csv.gz"
    existing = (pd.read_csv(prediction_path) if prediction_path.exists()
                and not args.force_models else pd.DataFrame())
    for season in SELECTION_SEASONS:
        base, _ = load_fold(store, season, output, manifest["dataset"]["sha256"],
                            manifest["model_source_sha256"], force=args.force_models)
        previous = existing[existing["season"] == season].copy() if not existing.empty else existing
        present = set(previous["variant_value"].unique()) if not previous.empty else set()
        variants = {}
        for half_life in RECENCY_HALF_LIVES:
            if half_life in present:
                continue
            candidate = copy.deepcopy(base)
            candidate["points"].player_recency_half_life = float(half_life)
            candidate["metadata"] = {**candidate.get("metadata", {}),
                                     "player_recency_half_life": float(half_life)}
            variants[half_life] = candidate
        fresh = (_event_rate_rows(store, season, variants) if variants else pd.DataFrame())
        detail = pd.concat([part for part in (previous, fresh) if not part.empty],
                           ignore_index=True)
        detail_rows.append(detail)
        for half_life, group in detail.groupby("variant_value"):
            result_rows.append({
                "season": season, "half_life_appearances": float(half_life),
                "rows": int(len(group)),
                "poisson_deviance": float(mean_poisson_deviance(
                    group["actual"], group["expected"])),
                "mae_count": float(np.mean(np.abs(group["actual"] - group["expected"]))),
                "bias_count": float(np.mean(group["expected"] - group["actual"])),
            })
        print(f"recency {season}: {len(detail):,} player-component rows", flush=True)

    metrics = pd.DataFrame(result_rows)
    aggregate = (metrics.groupby("half_life_appearances", as_index=False)
                 .agg({"rows": "sum", "poisson_deviance": "mean",
                       "mae_count": "mean", "bias_count": "mean"}))
    selected = float(aggregate.loc[aggregate["poisson_deviance"].idxmin(),
                                   "half_life_appearances"])
    payload = {
        "experiment_id": EXPERIMENT_ID,
        "source_sha256": manifest["source_sha256"],
        "dataset_sha256": manifest["dataset"]["sha256"],
        "selection_only": True,
        "primary_metric": "mean season Poisson deviance of goals+assists (lower is better)",
        "selected_half_life_appearances": selected,
        "by_season": metrics.to_dict("records"),
        "aggregate": aggregate.to_dict("records"),
    }
    _write_json(output / "recency-screen.json", payload)
    metrics.to_csv(output / "recency-screen-by-season.csv", index=False)
    aggregate.to_csv(output / "recency-screen-aggregate.csv", index=False)
    pd.concat(detail_rows, ignore_index=True).to_csv(
        prediction_path, index=False, compression="gzip")
    return payload


def _event_weight(output: Path) -> float:
    path = output / "event-screen.json"
    if not path.exists():
        raise FileNotFoundError("falta event-screen.json; ejecute screen-events primero")
    return float(json.loads(path.read_text(encoding="utf-8"))["selected_event_weight"])


def _recency_half_life(output: Path) -> float:
    path = output / "recency-screen.json"
    if not path.exists():
        raise FileNotFoundError("falta recency-screen.json; ejecute screen-recency primero")
    return float(json.loads(path.read_text(encoding="utf-8"))["selected_half_life_appearances"])


def run_variant(args, store: Store, output: Path, manifest: dict, season: str,
                name: str, spec: dict, event_weight: float, *, projector=None) -> dict:
    destination = output / "replays" / f"{season}-{name}.json"
    if destination.exists() and not args.force_replays:
        cached = json.loads(destination.read_text(encoding="utf-8"))
        if (cached.get("source_sha256") == manifest["source_sha256"]
                and cached.get("dataset_sha256") == manifest["dataset"]["sha256"]
                and cached.get("spec") == spec):
            return cached

    base, train = load_fold(store, season, output, manifest["dataset"]["sha256"],
                            manifest["model_source_sha256"],
                            force=args.force_models)
    if spec.get("recency"):
        base = copy.deepcopy(base)
        base["points"].player_recency_half_life = _recency_half_life(output)
    models = with_event_proxy(base, train, event_weight) if spec["events"] else base
    config = Config(
        policy=str(spec.get("policy", "milp")), projector="points",
        model_version=f"fold-{season}",
        horizon=int(spec["horizon"]), seed=42, chip_policy="none",
        decay=float(spec["decay"]), top_k=args.top_k, time_limit=args.time_limit,
        transfer_penalty=float(spec["transfer_penalty"]),
        uncertainty_transfer_weight=float(spec["uncertainty_transfer_weight"]),
    )
    if projector is not None and not spec["fixture"]:
        raise ValueError("un projector custom requiere spec.fixture=true")
    projector = projector if projector is not None else (
        FixtureProjector() if spec["fixture"] else None
    )
    (output / "replays").mkdir(parents=True, exist_ok=True)
    (output / "traces").mkdir(parents=True, exist_ok=True)
    trace = TraceWriter(output / "traces" / f"{season}-{name}.db")
    report = replay(
        season, "named", config, store=store, trace=trace,
        run_id=f"{manifest['experiment_id']}-{season}-{name}", max_gw=38, verbose=False,
        history_mode=spec["history_mode"], model_bundle=models,
        projection_fn=projector,
    )
    frame = report.to_frame().assign(season=season, variant=name)
    frame.to_csv(output / "replays" / f"{season}-{name}.csv", index=False)
    forecast = None
    if projector is not None:
        prediction_rows = []
        for (snapshot_season, gw), snapshot in projector.snapshots.items():
            truth = (store.results(snapshot_season, gw).groupby("element", as_index=False)
                     ["total_points"].sum().rename(columns={"total_points": "actual"}))
            scored = snapshot.merge(truth, on="element", how="left")
            scored["actual"] = scored["actual"].fillna(0.0)
            scored["season"], scored["gw"] = snapshot_season, gw
            prediction_rows.append(scored)
        predictions = pd.concat(prediction_rows, ignore_index=True)
        predictions.to_csv(output / "replays" / f"{season}-{name}-predictions.csv.gz",
                           index=False, compression="gzip")
        forecast = predictive_metrics(predictions)
    payload = {
        "experiment_id": manifest["experiment_id"],
        "source_sha256": manifest["source_sha256"],
        "dataset_sha256": manifest["dataset"]["sha256"],
        "season": season,
        "variant": name,
        "spec": spec,
        "event_weight": event_weight if spec["events"] else 0.0,
        "config": asdict(config),
        "points": report.total,
        "template": report.baselines.get("template"),
        "ceiling": report.baselines.get("ceiling"),
        "forecast_metrics": forecast,
        "gameweeks": report.gameweeks,
    }
    _write_json(destination, payload)
    print(f"replay {season} {name}: {report.total} pts", flush=True)
    return payload


def _policy_summary(records: list[dict], output: Path, manifest: dict) -> dict:
    totals = pd.DataFrame([{"season": r["season"], "variant": r["variant"],
                            "points": r["points"], "template": r["template"]}
                           for r in records])
    baseline = pd.concat([
        pd.DataFrame(r["gameweeks"])[["gw", "points"]].assign(season=r["season"])
        for r in records if r["variant"] == "control_h3"
    ], ignore_index=True)
    comparisons = {}
    for variant in sorted(set(totals["variant"]) - {"control_h3"}):
        candidate = pd.concat([
            pd.DataFrame(r["gameweeks"])[["gw", "points"]].assign(season=r["season"])
            for r in records if r["variant"] == variant
        ], ignore_index=True)
        comparisons[variant] = paired_policy_bootstrap(baseline, candidate)
    mean = totals.groupby("variant")["points"].mean().sort_values(ascending=False)
    control_mean = float(mean["control_h3"])
    eligible = []
    for name in sorted(set(totals["variant"]) - {"control_h3"}):
        paired = totals[totals["variant"].isin(["control_h3", name])].pivot(
            index="season", columns="variant", values="points")
        wins = int((paired[name] > paired["control_h3"]).sum())
        if float(mean[name]) > control_mean and wins >= 2:
            eligible.append(name)
    selected = max(eligible, key=lambda name: float(mean[name])) if eligible else "control_h3"
    payload = {
        "experiment_id": manifest["experiment_id"],
        "source_sha256": manifest["source_sha256"],
        "dataset_sha256": manifest["dataset"]["sha256"],
        "selection_only": True,
        "totals": totals.to_dict("records"),
        "mean_points": {str(k): float(v) for k, v in mean.items()},
        "paired_vs_control": comparisons,
        "selected_policy": selected,
        "selection_rule": "highest mean PVA among candidates winning >=2/3 development seasons",
    }
    _write_json(output / "policy-selection.json", payload)
    totals.to_csv(output / "policy-selection-totals.csv", index=False)
    return payload


def select_policy(args, store: Store, output: Path, manifest: dict) -> dict:
    weight = float(manifest["inherited_hyperparameters"]["event_proxy_weight"])
    records = []
    for season in SELECTION_SEASONS:
        for name, spec in POLICY_VARIANTS.items():
            records.append(run_variant(args, store, output, manifest, season,
                                       name, spec, weight))
    return _policy_summary(records, output, manifest)


def open_holdout(args, store: Store, output: Path, manifest: dict) -> dict:
    selection_path = output / "policy-selection.json"
    if not selection_path.exists():
        raise FileNotFoundError("falta policy-selection.json; seleccione politica antes del holdout")
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    candidate_name = str(selection["selected_policy"])
    if candidate_name == "control_h3":
        raise RuntimeError("ningun candidato supero al control en desarrollo; holdout permanece sellado")
    holdout_path = output / "holdout-result.json"
    if holdout_path.exists():
        sealed = json.loads(holdout_path.read_text(encoding="utf-8"))
        if (sealed.get("source_sha256") == manifest["source_sha256"]
                and sealed.get("dataset_sha256") == manifest["dataset"]["sha256"]
                and sealed.get("candidate") == candidate_name):
            return sealed
        raise RuntimeError("el holdout ya fue abierto bajo otro código/candidato; cree un nuevo experimento")
    weight = float(manifest["inherited_hyperparameters"]["event_proxy_weight"])
    records = [
        run_variant(args, store, output, manifest, HOLDOUT_SEASON,
                    "control_h3", POLICY_VARIANTS["control_h3"], weight),
        run_variant(args, store, output, manifest, HOLDOUT_SEASON,
                    candidate_name, POLICY_VARIANTS[candidate_name], weight),
    ]
    baseline, candidate = records
    payload = {
        "experiment_id": EXPERIMENT_ID,
        "source_sha256": manifest["source_sha256"],
        "dataset_sha256": manifest["dataset"]["sha256"],
        "holdout_opened_once": True,
        "season": HOLDOUT_SEASON,
        "candidate": candidate_name,
        "control_points": baseline["points"],
        "candidate_points": candidate["points"],
        "pva_38": int(candidate["points"] - baseline["points"]),
        "promotion": "not_authorized",
    }
    _write_json(holdout_path, payload)
    return payload


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("manifest", "screen-events", "screen-recency",
                                          "select-policy", "holdout"))
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
        if args.phase == "screen-events":
            result = screen_events(args, store, output, manifest)
        elif args.phase == "screen-recency":
            result = screen_recency(args, store, output, manifest)
        elif args.phase == "select-policy":
            result = select_policy(args, store, output, manifest)
        else:
            result = open_holdout(args, store, output, manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
