#!/usr/bin/env python3
"""Run the causal baseline / odds / events / combined ablation.

Nothing in this file is imported by production.  The experiment reuses the
released minutes and points artifacts, changing only the match context supplied
to the decomposed points model.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from experiments.odds_events.context import (
    add_baseline_lambdas,
    apply_event_factor,
    attach_market,
    blend_lambdas,
    build_event_factors,
    load_event_matches,
    load_fpl_matches,
    load_opening_market,
    match_metrics,
    paired_bootstrap_delta,
    select_event_spec,
    select_market_weight,
)
from mova_fpl.cli.eval_points import componentes_reales
from mova_fpl.data.store import Store
from mova_fpl.engine.projection import _proba_minutos
from mova_fpl.models.points import COMPONENTES, PointsModel
from mova_fpl.rules import get as get_rules


SEASONS = ("2020-21", "2021-22", "2022-23", "2023-24", "2024-25", "2025-26")
MARKET_TRAIN = ("2020-21", "2021-22", "2022-23", "2023-24")
HOLDOUTS = ("2024-25", "2025-26")
VARIANTS = ("baseline", "odds", "events", "both")


class ContextPointsModel(PointsModel):
    """Experimental wrapper that replaces only fixture scoring intensities."""

    def __init__(self, base: PointsModel, context: pd.DataFrame | None = None,
                 use_attack: bool = True, use_defense: bool = True):
        self.__dict__ = copy.deepcopy(base.__dict__)
        self._experiment_use_attack = use_attack
        self._experiment_use_defense = use_defense
        self._experiment_context = {}
        if context is not None:
            for row in context.itertuples(index=False):
                self._experiment_context[int(row.fixture)] = (
                    float(row.lambda_home), float(row.lambda_away))

    def _contexto_partido(self, roster, fuerza, equipos=None):
        base_mult, base_lam = super()._contexto_partido(roster, fuerza, equipos)
        if not self._experiment_context:
            return base_mult, base_lam

        new_mult, new_lam = base_mult.copy(), base_lam.copy()
        work = roster.reset_index(drop=True)
        fixtures = pd.to_numeric(work.get("fixture"), errors="coerce")
        homes = pd.to_numeric(work.get("was_home"), errors="coerce") == 1
        for fixture in fixtures.dropna().astype(int).unique():
            desired = self._experiment_context.get(int(fixture))
            if desired is None:
                continue
            lambda_home, lambda_away = desired
            in_fixture = fixtures == fixture
            home_mask = (in_fixture & homes).to_numpy()
            away_mask = (in_fixture & ~homes).to_numpy()
            if not home_mask.any() or not away_mask.any():
                continue

            # The opponent's conceded lambda is this team's attacking lambda.
            base_home_attack = float(np.nanmedian(base_lam[away_mask]))
            base_away_attack = float(np.nanmedian(base_lam[home_mask]))
            if self._experiment_use_attack and base_home_attack > 0:
                new_mult[home_mask] *= lambda_home / base_home_attack
            if self._experiment_use_attack and base_away_attack > 0:
                new_mult[away_mask] *= lambda_away / base_away_attack
            if self._experiment_use_defense:
                new_lam[home_mask] = lambda_away
                new_lam[away_mask] = lambda_home

        return np.clip(new_mult, 0.25, 3.0), np.clip(new_lam, 0.05, 5.5)


def context_for(frame: pd.DataFrame, prefix: str) -> pd.DataFrame:
    current = frame[frame["season"] == "2025-26"].copy()
    return current[["fixture", f"lambda_home_{prefix}", f"lambda_away_{prefix}"]].rename(
        columns={f"lambda_home_{prefix}": "lambda_home",
                 f"lambda_away_{prefix}": "lambda_away"})


def component_ablation(store: Store, minutes_model, base_points: PointsModel,
                       contexts: dict[str, pd.DataFrame], desde: int = 20,
                       hasta: int = 38) -> tuple[dict, pd.DataFrame]:
    scoring = get_rules("2025-26").SCORING
    models = {
        name: ContextPointsModel(base_points, None if name == "baseline" else contexts[name])
        for name in VARIANTS
    }
    rows = []
    for gw in range(desde, hasta + 1):
        history, roster = store.as_of("2025-26", gw), store.roster("2025-26", gw)
        result = store.results("2025-26", gw)
        if roster.empty or result.empty:
            continue
        minute_proba = _proba_minutos(history, roster, minutes_model)
        actual = componentes_reales(result, scoring)
        actual["gw"] = gw
        for name, model in models.items():
            predicted = model.project(history, roster, minute_proba, scoring,
                                      scoring.defcon_thresholds)
            predicted["gw"] = gw
            joined = predicted.merge(actual, on=["element", "gw"], how="left",
                                     suffixes=("_pred", "_real")).fillna(0.0)
            joined["variant"] = name
            rows.append(joined)
        print(f"components GW{gw:>2}: {len(roster):>3} players", flush=True)

    all_rows = pd.concat(rows, ignore_index=True)
    output = {}
    for name, data in all_rows.groupby("variant", sort=False):
        y, p = data["total_real"].to_numpy(float), data["xp"].to_numpy(float)
        component_bias = {}
        for component in COMPONENTES:
            pred_sum = float(data[f"{component}_pred"].sum())
            real_sum = float(data[f"{component}_real"].sum())
            component_bias[component] = {
                "predicted": pred_sum,
                "actual": real_sum,
                "relative_bias": ((pred_sum - real_sum) / abs(real_sum)) if real_sum else None,
            }
        output[name] = {
            "rows": int(len(data)),
            "xp_mae": float(np.mean(np.abs(p - y))),
            "xp_rmse": float(np.sqrt(np.mean((p - y) ** 2))),
            "pearson": float(np.corrcoef(p, y)[0, 1]),
            "spearman": float(spearmanr(p, y).statistic),
            "total_bias": float((p.sum() - y.sum()) / y.sum()),
            "component_bias": component_bias,
        }
    return output, all_rows


def _weekly_bootstrap(rows: list[dict], candidate: str, draws: int = 20_000,
                      seed: int = 42) -> dict:
    """Paired bootstrap of season points for independent weekly rebuilds."""
    delta = np.asarray([row[candidate] - row["baseline"] for row in rows], dtype=float)
    rng = np.random.default_rng(seed)
    samples = rng.choice(delta, size=(draws, len(delta)), replace=True).sum(axis=1)
    return {
        "delta": int(delta.sum()),
        "wins": int((delta > 0).sum()),
        "ties": int((delta == 0).sum()),
        "ci95": [float(v) for v in np.quantile(samples, [0.025, 0.975])],
        "bootstrap_p_le_zero": float((samples <= 0).mean()),
    }


def weekly_rebuild(store: Store, minutes_model, models: dict[str, ContextPointsModel]) -> dict:
    """Rebuild a legal 15-player squad independently for every gameweek.

    This deliberately removes transfer-path dependence.  It is not a playable
    season score; it answers the narrower question whether a candidate xP model
    ranks the weekly player pool better than the baseline.
    """
    from mova_fpl.engine.evaluate import score_decision
    from mova_fpl.engine.runner import Config, decide
    from mova_fpl.engine.simulator import _candidates
    from mova_fpl.engine.state import State

    season = "2025-26"
    rules = get_rules(season).SQUAD
    config = Config(policy="milp", projector="points", model_version="1.0.0",
                    horizon=1, seed=42, chip_policy="none")
    rows = []
    for gw in range(1, 39):
        history, roster = store.as_of(season, gw), store.roster(season, gw)
        results = store.results(season, gw)
        if roster.empty or results.empty:
            continue
        minute_proba = _proba_minutos(history, roster, minutes_model)
        row = {"gw": gw}
        for name, model in models.items():
            scoring = get_rules(season).SCORING
            detail = model.project(history, roster, minute_proba, scoring,
                                   scoring.defcon_thresholds)
            candidates = _candidates(roster, pd.Series(detail["xp"].to_numpy(float)))
            xp = {gw: {c.element: c.xp for c in candidates}}
            state = State(season=season, gw=gw, candidates=candidates, squad=None,
                          free_transfers=1, bank=0.0, rules=rules, horizon_xp=xp)
            decision = decide(gw, state, config)
            known = {c.element: {"position": c.position, "team": c.team, "price": c.price}
                     for c in candidates}
            outcome = score_decision(decision, results, rules, known)
            row[name] = outcome.points
            row[f"{name}_captain"] = outcome.captain_points
        rows.append(row)
        print(f"weekly rebuild GW{gw:>2}", flush=True)

    totals = {name: int(sum(row[name] for row in rows)) for name in models}
    captains = {name: int(sum(row[f"{name}_captain"] for row in rows)) for name in models}
    paired = {name: _weekly_bootstrap(rows, name) for name in models if name != "baseline"}
    return {"method": "independent_cold_start_each_gw", "totals": totals,
            "captains": captains, "paired": paired, "weekly": rows}


def run_backtest(name: str, model: ContextPointsModel, output_dir: Path,
                 horizon: int = 3, mode: str = "named") -> dict:
    """Use the exact production replay/optimizer with a temporary projector hook."""
    import mova_fpl.engine.simulator as simulator
    from mova_fpl.engine.runner import Config
    from mova_fpl.engine.simulator import replay
    from mova_fpl.trace import TraceWriter

    original = simulator.points_projection

    def experimental_projection(history, roster, modelos, season, con_desglose=False,
                                equipos=None, disponibilidad=None):
        proba = _proba_minutos(history, roster, modelos["minutes"])
        scoring = get_rules(season).SCORING
        detail = model.project(history, roster, proba, scoring,
                               scoring.defcon_thresholds, equipos=equipos)
        xp = pd.Series(detail["xp"].to_numpy(float), dtype=float)
        return (xp, detail) if con_desglose else xp

    simulator.points_projection = experimental_projection
    try:
        trace_path = output_dir / f"trace-{name}-h{horizon}.db"
        report = replay(
            "2025-26", mode,
            Config(policy="milp", projector="points", model_version="1.0.0",
                   horizon=horizon, seed=42, chip_policy="none"),
            trace=TraceWriter(trace_path),
            run_id=f"odds-events-{name}-{mode}-h{horizon}", verbose=False,
        )
    finally:
        simulator.points_projection = original
    return {
        "points": report.total,
        "template": report.baselines.get("template"),
        "ceiling": report.baselines.get("ceiling"),
        "mode": mode,
        "run_id": report.run_id,
        "gameweeks": report.gameweeks,
    }


def prepare(args) -> tuple[pd.DataFrame, dict, dict]:
    store = Store(args.fpl_db)
    matches = load_fpl_matches(args.fpl_db, SEASONS)
    market = load_opening_market(args.odds_dir, SEASONS)
    frame = add_baseline_lambdas(attach_market(matches, market), store)
    if frame["lambda_home_market"].isna().any():
        raise RuntimeError("market join is incomplete")

    market_weight, market_grid = select_market_weight(frame, MARKET_TRAIN)
    frame = blend_lambdas(frame, market_weight, "odds")

    events = load_event_matches(args.events_db, matches)
    event_factors = build_event_factors(matches, events)
    frame = frame.merge(event_factors, on=["season", "gw", "fixture"], how="left")

    event_set, event_exponent, event_grid = select_event_spec(frame, "baseline")
    both_set, both_exponent, both_grid = select_event_spec(frame, "odds")
    frame = apply_event_factor(frame, "baseline", event_set, event_exponent, "events")
    frame = apply_event_factor(frame, "odds", both_set, both_exponent, "both")

    selection = {
        "market_weight": market_weight,
        "market_train_seasons": MARKET_TRAIN,
        "events": {"feature_set": event_set, "exponent": event_exponent,
                   "validation_gws": "10-19"},
        "both": {"feature_set": both_set, "exponent": both_exponent,
                 "validation_gws": "10-19"},
        "market_grid": market_grid.to_dict("records"),
        "event_grid": event_grid.to_dict("records"),
        "both_grid": both_grid.to_dict("records"),
    }
    coverage = {
        "fpl_matches": int(len(matches)),
        "market_matches": int(frame["lambda_home_market"].notna().sum()),
        "event_matches": int(len(events)),
        "market_fit_rmse_mean": float(frame["market_fit_rmse"].mean()),
        "event_last_gw": int(events["gw"].max()),
    }
    return frame, selection, coverage


def match_ablation(frame: pd.DataFrame) -> dict:
    output = {"holdouts": {}, "events_test": {}}
    for season in HOLDOUTS:
        test = frame[frame["season"] == season]
        output["holdouts"][season] = {
            prefix: match_metrics(test, prefix)
            for prefix in ("baseline", "market", "odds")
        }

    # Feature selection used GW10-19.  This later window is untouched by selection.
    event_test = frame[(frame["season"] == "2025-26") & frame["gw"].between(20, 29)]
    for prefix in ("baseline", "odds", "events", "both"):
        output["events_test"][prefix] = match_metrics(event_test, prefix)
    output["events_test"]["paired_bootstrap"] = {
        candidate: {
            metric: paired_bootstrap_delta(event_test, candidate, "baseline", metric)
            for metric in ("poisson_deviance", "cs_brier")
        }
        for candidate in ("odds", "events", "both")
    }
    return output


def render_markdown(result: dict) -> str:
    selection, coverage = result["selection"], result["coverage"]
    lines = [
        "# Ablation causal: baseline vs odds vs eventos",
        "",
        f"Git: `{result['git_sha']}` · generated `{result['generated_at']}`",
        "",
        "## Cobertura y selección",
        "",
        f"- FPL: {coverage['fpl_matches']:,} partidos; odds: {coverage['market_matches']:,}; "
        f"eventos mapeados: {coverage['event_matches']:,} hasta GW{coverage['event_last_gw']}.",
        f"- Peso del mercado seleccionado sólo en 2020/21–2023/24: "
        f"**{selection['market_weight']:.2f}**.",
        f"- Eventos: `{selection['events']['feature_set']}` con exponente "
        f"{selection['events']['exponent']:.2f}; combinado: "
        f"`{selection['both']['feature_set']}` / {selection['both']['exponent']:.2f}.",
        "",
        "Las odds son el consenso *pre-closing*. Las columnas de cierre no entraron. "
        "Los eventos de una GW sólo actualizan features desde la siguiente GW.",
        "",
        "## Modelo de partido — holdouts completos",
        "",
        "| Temporada | Variante | Poisson dev. | CS Brier | CS log-loss | RPS 1X2 |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for season, variants in result["match"]["holdouts"].items():
        for name, metrics in variants.items():
            lines.append(f"| {season} | {name} | {metrics['poisson_deviance']:.4f} | "
                         f"{metrics['cs_brier']:.4f} | {metrics['cs_logloss']:.4f} | "
                         f"{metrics['rps_1x2']:.4f} |")

    lines += ["", "## Eventos — test no usado en selección (GW20–29)", "",
              "| Variante | Poisson dev. | CS Brier | CS log-loss | RPS 1X2 |",
              "|---|---:|---:|---:|---:|"]
    for name in ("baseline", "odds", "events", "both"):
        m = result["match"]["events_test"][name]
        lines.append(f"| {name} | {m['poisson_deviance']:.4f} | {m['cs_brier']:.4f} | "
                     f"{m['cs_logloss']:.4f} | {m['rps_1x2']:.4f} |")

    lines += ["", "## xP descompuesto — 2025/26 GW20–38", "",
              "| Variante | MAE xP | RMSE | Pearson | Spearman | Sesgo total | Sesgo CS |",
              "|---|---:|---:|---:|---:|---:|---:|"]
    for name in VARIANTS:
        m = result["components"][name]
        cs = m["component_bias"]["pts_cs"]["relative_bias"]
        lines.append(f"| {name} | {m['xp_mae']:.4f} | {m['xp_rmse']:.4f} | "
                     f"{m['pearson']:.4f} | {m['spearman']:.4f} | "
                     f"{100*m['total_bias']:+.2f}% | {100*cs:+.2f}% |")

    if result.get("backtest"):
        mode = next(iter(result["backtest"].values())).get("mode", "unknown")
        lines += ["", f"## Mismo optimizador — MILP h=3, modo {mode}", "",
                  "| Variante | Puntos | vs baseline | Template |",
                  "|---|---:|---:|---:|"]
        base = result["backtest"]["baseline"]["points"]
        for name in VARIANTS:
            m = result["backtest"][name]
            lines.append(f"| {name} | **{m['points']:,}** | {m['points']-base:+d} | "
                         f"{m['template']:,} |")
    if result.get("weekly_rebuild"):
        weekly = result["weekly_rebuild"]
        lines += ["", "## Ranking aislado — plantilla reconstruida cada GW", "",
                  "Este control elimina transferencias y trayectoria. No es una puntuación "
                  "jugable; mide la calidad del ranking semanal.", "",
                  "| Variante | Puntos | vs baseline | GW ganadas | IC95 delta |",
                  "|---|---:|---:|---:|---:|"]
        base = weekly["totals"]["baseline"]
        for name, total in weekly["totals"].items():
            if name == "baseline":
                lines.append(f"| {name} | **{total:,}** | — | — | — |")
                continue
            paired = weekly["paired"][name]
            low, high = paired["ci95"]
            lines.append(f"| {name} | **{total:,}** | {total-base:+d} | "
                         f"{paired['wins']}/38 | [{low:+.0f}, {high:+.0f}] |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fpl-db", type=Path, required=True)
    parser.add_argument("--odds-dir", type=Path, required=True)
    parser.add_argument("--events-db", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--skip-backtest", action="store_true")
    parser.add_argument("--weekly-rebuild", action="store_true",
                        help="also isolate weekly ranking with a fresh squad every GW")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    os.environ["MOVA_CANONICAL_DB"] = str(args.fpl_db)
    os.environ["MOVA_MODEL_ROOT"] = str(args.model_root)
    # ``eval_points`` imports the registry before CLI arguments are known.
    # Redirect the already-imported module explicitly; no artifact is written.
    import mova_fpl.models.registry as registry
    registry.ARTIFACTS = args.model_root

    frame, selection, coverage = prepare(args)
    match = match_ablation(frame)

    minutes = joblib.load(args.model_root / "minutes/minutes-1.0.0.joblib")
    points = joblib.load(args.model_root / "points/points-1.0.0.joblib")
    contexts = {name: context_for(frame, name) for name in ("odds", "events", "both")}
    components, component_rows = component_ablation(Store(args.fpl_db), minutes, points, contexts)
    component_rows.to_csv(args.output_dir / "component_predictions.csv", index=False)

    result = {
        "schema_version": "mova-odds-events-ablation-v1",
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "git_sha": os.popen("git rev-parse --short HEAD").read().strip(),
        "coverage": coverage,
        "selection": selection,
        "match": match,
        "components": components,
    }

    if not args.skip_backtest:
        result["backtest"] = {}
        models = {
            "baseline": ContextPointsModel(points),
            **{name: ContextPointsModel(points, contexts[name]) for name in ("odds", "events", "both")},
        }
        for name in VARIANTS:
            print(f"backtest {name}...", flush=True)
            result["backtest"][name] = run_backtest(name, models[name], args.output_dir)

    if args.weekly_rebuild:
        ranking_models = {
            "baseline": ContextPointsModel(points),
            "odds": ContextPointsModel(points, contexts["odds"]),
            "odds_cs": ContextPointsModel(points, contexts["odds"],
                                           use_attack=False, use_defense=True),
            "odds_attack": ContextPointsModel(points, contexts["odds"],
                                               use_attack=True, use_defense=False),
        }
        result["weekly_rebuild"] = weekly_rebuild(Store(args.fpl_db), minutes, ranking_models)

    (args.output_dir / "results.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, default=float) + "\n", encoding="utf-8")
    report = render_markdown(result)
    (args.output_dir / "report.md").write_text(report, encoding="utf-8")
    print("\n" + report)


if __name__ == "__main__":
    main()
