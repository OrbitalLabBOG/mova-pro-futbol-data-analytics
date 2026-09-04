#!/usr/bin/env python3
"""Ensemble causal de cambio de regimen para minutos y xP.

Combina dos pronosticos que representan incertidumbre epistemica sobre el
inicio de temporada: continuidad con el cierre anterior y reinicio con solo las
jornadas cerradas de la temporada actual. El peso se selecciona exclusivamente
en temporadas de desarrollo antes de abrir 2025-26.
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
from experiments.long_horizon.season_boundary import (
    BoundaryStore,
    DEVELOPMENT_SEASONS,
    EVALUATION_GWS,
    EXTERNAL_SEASON,
    _file_spec,
    _prediction_rows,
    predictive_metrics,
)
from mova_fpl.engine.projection import fixture_horizon_projection
from mova_fpl.engine.runner import Config
from mova_fpl.engine.simulator import ProjectionBundle, replay
from mova_fpl.trace import TraceWriter


EXPERIMENT_ID = "EXP-MOVA-2026-017"
PARENT_EXPERIMENT_ID = "EXP-MOVA-2026-013"
ALPHAS_FULL = (0.25, 0.50, 0.75)
DEFAULT_EXPERIMENTS = Path(__file__).resolve().parents[3] / "mova-fpl-experiments"
DEFAULT_OUTPUT = DEFAULT_EXPERIMENTS / EXPERIMENT_ID
DEFAULT_PARENT = DEFAULT_EXPERIMENTS / PARENT_EXPERIMENT_ID


class ForecastEnsembleProjector:
    """Mezcla continuidad y reinicio sin leer resultados futuros.

    ``alpha_full`` pondera el pronostico con la temporada anterior completa; el
    complemento pondera el pronostico que usa solo jornadas actuales cerradas.
    Las desviaciones se combinan como varianza total de una mezcla de dos
    distribuciones, por lo que tambien reflejan desacuerdo entre regimenes.
    """

    def __init__(self, alpha_full: float):
        if not 0.0 <= alpha_full <= 1.0:
            raise ValueError("alpha_full debe estar en [0, 1]")
        self.alpha_full = float(alpha_full)
        self.snapshots: dict[tuple[str, int], pd.DataFrame] = {}

    @staticmethod
    def _blend_map(full: dict[int, float], reset: dict[int, float], alpha: float):
        keys = set(full) | set(reset)
        return {
            int(key): alpha * float(full.get(key, 0.0))
            + (1.0 - alpha) * float(reset.get(key, 0.0))
            for key in keys
        }

    def __call__(self, *, history, roster, models, season, gw, store, config,
                 max_gw, alias) -> ProjectionBundle:
        if alias:
            raise ValueError("ForecastEnsembleProjector requiere mode='named'")
        until = min(int(max_gw), int(gw) + int(config.horizon) - 1)
        current = roster.drop_duplicates("element", keep="first").copy()
        current_history = history[
            history["season"].astype(str).eq(str(season))
        ].copy() if not history.empty and "season" in history else history.iloc[0:0].copy()
        schedule = store.team_fixtures(season, gw, until)
        common = {
            "roster": current,
            "modelos": models,
            "season": season,
            "gw": gw,
            "horizon": until - int(gw) + 1,
            "schedule": schedule,
            "decay": config.decay,
        }
        full = fixture_horizon_projection(history=history, **common)
        reset = fixture_horizon_projection(history=current_history, **common)
        alpha = self.alpha_full
        horizon_xp = {
            target_gw: self._blend_map(
                full.horizon_xp.get(target_gw, {}),
                reset.horizon_xp.get(target_gw, {}),
                alpha,
            )
            for target_gw in range(int(gw), until + 1)
        }
        horizon_sd: dict[int, dict[int, float]] = {}
        for target_gw in range(int(gw), until + 1):
            means_full = full.horizon_xp.get(target_gw, {})
            means_reset = reset.horizon_xp.get(target_gw, {})
            sd_full = full.horizon_sd.get(target_gw, {})
            sd_reset = reset.horizon_sd.get(target_gw, {})
            mixed = horizon_xp[target_gw]
            horizon_sd[target_gw] = {}
            for element, mean in mixed.items():
                second = (
                    alpha * (float(sd_full.get(element, 0.0)) ** 2
                             + float(means_full.get(element, 0.0)) ** 2)
                    + (1.0 - alpha) * (float(sd_reset.get(element, 0.0)) ** 2
                                       + float(means_reset.get(element, 0.0)) ** 2)
                )
                horizon_sd[target_gw][element] = float(
                    np.sqrt(max(0.0, second - float(mean) ** 2))
                )

        detail = full.current_detail.copy()
        if not detail.empty:
            detail["xp_full"] = detail["element"].map(
                full.horizon_xp.get(int(gw), {})).fillna(0.0)
            detail["xp_reset"] = detail["element"].map(
                reset.horizon_xp.get(int(gw), {})).fillna(0.0)
            detail["xp"] = detail["element"].map(
                horizon_xp.get(int(gw), {})).fillna(0.0)
            detail["xp_sd"] = detail["element"].map(
                horizon_sd.get(int(gw), {})).fillna(0.0)
            detail["regime_disagreement"] = (
                detail["xp_full"] - detail["xp_reset"]
            ).abs()
        self.snapshots[(str(season), int(gw))] = detail
        ids = current["element"].astype(int)
        xp = ids.map(horizon_xp.get(int(gw), {})).fillna(0.0)
        return ProjectionBundle(
            xp=pd.Series(xp.to_numpy(dtype=float), dtype=float),
            horizon_xp=horizon_xp,
            horizon_sd=horizon_sd,
        )


def freeze_manifest(args, output: Path) -> dict:
    root = Path(__file__).resolve().parents[2]
    db = Path(args.fpl_db).resolve()
    parent = Path(args.parent_output).resolve()
    parent_manifest_path = parent / "manifest.json"
    parent_payload = json.loads(parent_manifest_path.read_text(encoding="utf-8"))
    paths = {
        season: Path(parent_payload["fold_models"][season]["path"])
        for season in (*DEVELOPMENT_SEASONS, EXTERNAL_SEASON)
    }
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
        "parent_manifest": _file_spec(parent_manifest_path),
        "fold_models": {season: _file_spec(path) for season, path in paths.items()},
        "development_seasons": list(DEVELOPMENT_SEASONS),
        "external_evaluation_season": EXTERNAL_SEASON,
        "evaluation_gws": list(EVALUATION_GWS),
        "alpha_full_candidates": list(ALPHAS_FULL),
        "control": "append_full forecast (alpha_full=1.0)",
        "candidate": "convex forecast ensemble of append_full and current_reset",
        "primary_metric": "pooled three-class minutes log loss over GW2-GW8",
        "selection_gate": (
            "candidate must improve control log loss in every development season, "
            "not worsen pooled p60 Brier, then minimize pooled log loss"
        ),
        "decision_gate": (
            "positive mean PVA-38 and wins in at least two of three development seasons"
        ),
        "external_gate": (
            "selected candidate improves log loss and p60 Brier and has positive PVA-38"
        ),
        "policy": {"name": "season_fixture_h3", "horizon": 3, "decay": 0.84,
                   "chips": "none"},
        "classification": "causal forecast ensemble; no synthetic efficacy data",
        "promotion": "forbidden; explicit review required",
        "known_limitations": [
            "three development seasons are available for comparable policy replay",
            "2025-26 was inspected by earlier experiments and is not cognitively pristine",
            "forecast mixture represents regime uncertainty but not player correlations",
            "historical fixture replay retains final postponement scheduling",
        ],
        "research_basis": [
            "West, Harrison & Migon (1985), Dynamic Generalized Linear Models",
            "Gneiting & Raftery (2007), Strictly Proper Scoring Rules",
            "Bates & Granger (1969), The Combination of Forecasts",
        ],
    }
    destination = output / "manifest.json"
    if destination.exists():
        existing = json.loads(destination.read_text(encoding="utf-8"))
        without_time = lambda value: {k: v for k, v in value.items() if k != "created_at"}
        if without_time(existing) != without_time(payload):
            raise RuntimeError(f"{EXPERIMENT_ID} ya existe bajo otros inputs")
        return existing
    _write_json(destination, payload)
    return payload


def _prediction_blends(store, model, season: str) -> pd.DataFrame:
    raw = _prediction_rows(
        store, model, season, ("current_reset", "append_full"),
    )
    key = ["season", "gw", "element", "player_key", "position", "actual_class"]
    full = raw[raw["variant"].eq("append_full")].set_index(key).sort_index()
    reset = raw[raw["variant"].eq("current_reset")].set_index(key).sort_index()
    if not full.index.equals(reset.index):
        raise RuntimeError("los brazos predictivos no tienen las mismas filas")
    output = []
    for alpha in (1.0, *ALPHAS_FULL):
        probability = (
            alpha * full[["p0", "p1", "p60"]].to_numpy(dtype=float)
            + (1.0 - alpha) * reset[["p0", "p1", "p60"]].to_numpy(dtype=float)
        )
        frame = full.reset_index()[key].copy()
        frame[["p0", "p1", "p60"]] = probability
        frame["alpha_full"] = float(alpha)
        frame["variant"] = "control_full" if alpha == 1.0 else f"blend_{alpha:.2f}"
        output.append(frame)
    return pd.concat(output, ignore_index=True)


def _metrics(predictions: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (season, variant, alpha), frame in predictions.groupby(
            ["season", "variant", "alpha_full"], sort=True):
        rows.append({
            "season": season,
            "variant": variant,
            "alpha_full": float(alpha),
            **predictive_metrics(frame),
        })
    return pd.DataFrame(rows)


def select_predictive(args, output: Path, manifest: dict) -> dict:
    store = CachedStore(args.fpl_db)
    frames = []
    for season in DEVELOPMENT_SEASONS:
        model = joblib.load(Path(manifest["fold_models"][season]["path"]))["minutes"]
        frames.append(_prediction_blends(store, model, season))
    predictions = pd.concat(frames, ignore_index=True)
    metrics = _metrics(predictions)
    pooled = []
    for (variant, alpha), frame in predictions.groupby(
            ["variant", "alpha_full"], sort=True):
        pooled.append({"variant": variant, "alpha_full": float(alpha),
                       **predictive_metrics(frame)})
    pooled = pd.DataFrame(pooled).set_index("variant")
    by_season = metrics.pivot(index="season", columns="variant", values="log_loss_3c")
    eligible = []
    for alpha in ALPHAS_FULL:
        name = f"blend_{alpha:.2f}"
        if (bool((by_season[name] < by_season["control_full"]).all())
                and pooled.loc[name, "brier_p60"] <= pooled.loc["control_full", "brier_p60"]):
            eligible.append(name)
    selected = min(eligible, key=lambda name: float(pooled.loc[name, "log_loss_3c"])) \
        if eligible else "control_full"
    payload = {
        "experiment_id": EXPERIMENT_ID,
        "source_sha256": manifest["source_sha256"],
        "dataset_sha256": manifest["dataset"]["sha256"],
        "selected_variant": selected,
        "selected_alpha_full": (
            float(pooled.loc[selected, "alpha_full"]) if selected != "control_full" else 1.0
        ),
        "eligible_candidates": eligible,
        "candidate_accepted": selected != "control_full",
        "pooled_metrics": pooled.reset_index().to_dict("records"),
        "season_metrics": metrics.to_dict("records"),
        "promotion": "not_authorized",
    }
    predictions.to_csv(output / "development-predictions.csv.gz", index=False,
                       compression="gzip")
    metrics.to_csv(output / "development-metrics.csv", index=False)
    _write_json(output / "selection.json", payload)
    return payload


def _load_selection(output: Path, manifest: dict) -> dict:
    payload = json.loads((output / "selection.json").read_text(encoding="utf-8"))
    if (payload.get("source_sha256") != manifest["source_sha256"]
            or payload.get("dataset_sha256") != manifest["dataset"]["sha256"]):
        raise RuntimeError("selection no pertenece al manifest")
    if not payload.get("candidate_accepted"):
        raise RuntimeError("ningun ensemble supero el gate predictivo")
    return payload


def _run_policy(args, output: Path, manifest: dict, season: str,
                variant: str, alpha: float) -> dict:
    destination = output / "replays" / f"{season}-{variant}.json"
    if destination.exists() and not args.force_replays:
        cached = json.loads(destination.read_text(encoding="utf-8"))
        if (cached.get("source_sha256") == manifest["source_sha256"]
                and cached.get("dataset_sha256") == manifest["dataset"]["sha256"]):
            return cached
        raise RuntimeError(f"replay incompatible: {destination}")
    bundle = joblib.load(Path(manifest["fold_models"][season]["path"]))
    store = BoundaryStore(args.fpl_db, "append_full")
    projector = FixtureProjector() if variant == "control_full" \
        else ForecastEnsembleProjector(alpha)
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
        history_mode="season", model_bundle=bundle, projection_fn=projector,
    )
    payload = {
        "experiment_id": EXPERIMENT_ID,
        "source_sha256": manifest["source_sha256"],
        "dataset_sha256": manifest["dataset"]["sha256"],
        "model_sha256": manifest["fold_models"][season]["sha256"],
        "season": season,
        "variant": variant,
        "alpha_full": float(alpha),
        "config": asdict(config),
        "points": int(report.total),
        "gameweeks": report.gameweeks,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    report.to_frame().to_csv(output / "replays" / f"{season}-{variant}.csv", index=False)
    _write_json(destination, payload)
    print(f"replay {season} {variant}: {report.total} pts", flush=True)
    return payload


def _decision_summary(records: list[dict], candidate: str) -> dict:
    totals = pd.DataFrame([
        {"season": row["season"], "variant": row["variant"], "points": row["points"]}
        for row in records
    ])
    pivot = totals.pivot(index="season", columns="variant", values="points")
    deltas = pivot[candidate] - pivot["control_full"]
    frames = {}
    for variant in ("control_full", candidate):
        frames[variant] = pd.concat([
            pd.DataFrame(row["gameweeks"])[["gw", "points"]].assign(season=row["season"])
            for row in records if row["variant"] == variant
        ], ignore_index=True)
    return {
        "candidate": candidate,
        "totals": totals.to_dict("records"),
        "delta_by_season": {str(k): int(v) for k, v in deltas.items()},
        "wins": int((deltas > 0).sum()),
        "losses": int((deltas < 0).sum()),
        "mean_delta": float(deltas.mean()),
        "paired_bootstrap": paired_policy_bootstrap(
            frames["control_full"], frames[candidate], draws=50_000,
            block_size=4, seed=42,
        ),
    }


def decision_development(args, output: Path, manifest: dict) -> dict:
    selection = _load_selection(output, manifest)
    candidate = str(selection["selected_variant"])
    alpha = float(selection["selected_alpha_full"])
    records = [
        _run_policy(args, output, manifest, season, variant, alpha)
        for season in DEVELOPMENT_SEASONS
        for variant in ("control_full", candidate)
    ]
    summary = _decision_summary(records, candidate)
    summary |= {
        "experiment_id": EXPERIMENT_ID,
        "source_sha256": manifest["source_sha256"],
        "dataset_sha256": manifest["dataset"]["sha256"],
        "candidate_accepted": bool(summary["mean_delta"] > 0 and summary["wins"] >= 2),
        "promotion": "not_authorized",
    }
    _write_json(output / "decision-development.json", summary)
    return summary


def external_evaluation(args, output: Path, manifest: dict) -> dict:
    destination = output / "external-evaluation.json"
    selection = _load_selection(output, manifest)
    decision_dev = json.loads((output / "decision-development.json").read_text())
    if not decision_dev.get("candidate_accepted"):
        raise RuntimeError("el ensemble no supero el gate decisional")
    candidate = str(selection["selected_variant"])
    alpha = float(selection["selected_alpha_full"])
    if destination.exists():
        sealed = json.loads(destination.read_text(encoding="utf-8"))
        if (sealed.get("source_sha256") == manifest["source_sha256"]
                and sealed.get("candidate") == candidate):
            return sealed
        raise RuntimeError("evaluacion externa incompatible ya existe")
    store = CachedStore(args.fpl_db)
    model = joblib.load(Path(manifest["fold_models"][EXTERNAL_SEASON]["path"]))["minutes"]
    predictions = _prediction_blends(store, model, EXTERNAL_SEASON)
    predictions = predictions[predictions["variant"].isin(("control_full", candidate))]
    metrics = _metrics(predictions)
    by_variant = metrics.set_index("variant")
    records = [
        _run_policy(args, output, manifest, EXTERNAL_SEASON, variant, alpha)
        for variant in ("control_full", candidate)
    ]
    decision = _decision_summary(records, candidate)
    log_delta = float(by_variant.loc[candidate, "log_loss_3c"]
                      - by_variant.loc["control_full", "log_loss_3c"])
    p60_delta = float(by_variant.loc[candidate, "brier_p60"]
                      - by_variant.loc["control_full", "brier_p60"])
    pva = int(decision["delta_by_season"][EXTERNAL_SEASON])
    accepted = bool(log_delta < 0 and p60_delta < 0 and pva > 0)
    predictions.to_csv(output / "external-predictions.csv.gz", index=False,
                       compression="gzip")
    metrics.to_csv(output / "external-metrics.csv", index=False)
    payload = {
        "experiment_id": EXPERIMENT_ID,
        "source_sha256": manifest["source_sha256"],
        "dataset_sha256": manifest["dataset"]["sha256"],
        "external_opened_once": True,
        "season": EXTERNAL_SEASON,
        "candidate": candidate,
        "alpha_full": alpha,
        "predictive_metrics": metrics.to_dict("records"),
        "log_loss_delta_vs_control": log_delta,
        "p60_brier_delta_vs_control": p60_delta,
        "decision": decision,
        "pva_38": pva,
        "candidate_accepted": accepted,
        "promotion": "not_authorized; review required",
    }
    _write_json(destination, payload)
    return payload


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=(
        "manifest", "select", "decision-development", "external",
    ))
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
