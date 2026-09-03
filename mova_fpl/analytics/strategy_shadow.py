"""Liquidación y gate MLOps del comparador estratégico no ejecutable."""
from __future__ import annotations

from math import erf, pi, sqrt

import numpy as np
import pandas as pd

from mova_fpl.engine.discrete_uncertainty import (
    discrete_metrics, normal_discrete_pmf,
)
from mova_fpl.engine.evaluate import collapse_results, score_decision
from mova_fpl.engine.state import Decision
from mova_fpl.rules import get as get_rules
from mova_fpl.rules.base import Position

SCHEMA = "mova-strategy-shadow-settlement-v1"
GATE_SCHEMA = "mova-strategy-shadow-gate-v1"
CENTRAL_Z = {"50": 0.6744897501960817, "80": 1.2815515655446004,
             "90": 1.6448536269514722}


def _row(matrix: dict, gw: int) -> dict[int, float]:
    raw = matrix.get(str(gw), matrix.get(gw))
    if raw is None:
        raise ValueError(f"proyección sin GW{gw}")
    return {int(element): float(value) for element, value in raw.items()}


def _normal_crps(actual: np.ndarray, mean: np.ndarray, sd: np.ndarray) -> np.ndarray:
    """CRPS de una Normal, con límite exacto MAE cuando sd=0."""
    output = np.abs(actual - mean)
    positive = sd > 1e-12
    if not positive.any():
        return output
    z = (actual[positive] - mean[positive]) / sd[positive]
    phi = np.exp(-0.5 * z ** 2) / sqrt(2.0 * pi)
    cdf = 0.5 * (1.0 + np.asarray([erf(value / sqrt(2.0)) for value in z]))
    output[positive] = sd[positive] * (
        z * (2.0 * cdf - 1.0) + 2.0 * phi - 1.0 / sqrt(pi)
    )
    return output


def _forecast_metrics(mean: dict[int, float], actual: dict[int, int],
                      sd: dict[int, float] | None = None) -> dict:
    missing = sorted(set(mean) - set(actual))
    if missing:
        raise ValueError(
            f"resultado oficial incompleto: faltan {len(missing)} elementos proyectados"
        )
    ids = sorted(mean)
    observed = np.asarray([actual[element] for element in ids], dtype=float)
    expected = np.asarray([mean[element] for element in ids], dtype=float)
    error = expected - observed
    spearman = (
        float(pd.Series(expected).corr(pd.Series(observed), method="spearman"))
        if np.ptp(expected) > 1e-12 and np.ptp(observed) > 1e-12 else float("nan")
    )
    metrics = {
        "rows": len(ids),
        "mae": round(float(np.mean(np.abs(error))), 7),
        "rmse": round(float(np.sqrt(np.mean(error ** 2))), 7),
        "bias": round(float(np.mean(error)), 7),
        "spearman": round(spearman, 7) if np.isfinite(spearman) else None,
    }
    if sd is None:
        return metrics
    missing_sd = sorted(set(mean) - set(sd))
    if missing_sd:
        raise ValueError(f"incertidumbre incompleta: faltan {len(missing_sd)} elementos")
    sigma = np.asarray([max(0.0, sd[element]) for element in ids], dtype=float)
    metrics["crps_normal"] = round(float(np.mean(
        _normal_crps(observed, expected, sigma)
    )), 7)
    for label, z_value in CENTRAL_Z.items():
        covered = np.abs(observed - expected) <= z_value * sigma
        metrics[f"coverage_{label}"] = round(float(np.mean(covered)), 7)
    return metrics


def _discrete_forecast_metrics(distribution: dict, *, mean: dict[int, float],
                               sd: dict[int, float], actual: dict[int, int]) -> dict:
    if distribution.get("schema") != "mova-discrete-shadow-v1":
        raise ValueError("distribución discreta incompatible")
    if (distribution.get("selected_for_execution") is not False
            or distribution.get("optimization_mean_unchanged") is not True):
        raise ValueError("distribución discreta adquirió autoridad operativa")
    support = np.asarray(distribution.get("support") or (), dtype=int)
    rows = {int(element): row for element, row in (distribution.get("rows") or {}).items()}
    ids = sorted(mean)
    if set(rows) != set(ids):
        raise ValueError("distribución discreta no cubre los mismos elementos")
    if any(element not in actual for element in ids):
        raise ValueError("faltan resultados oficiales para distribución discreta")
    probabilities = np.asarray([rows[element]["pmf"] for element in ids], dtype=float)
    observed = np.asarray([actual[element] for element in ids], dtype=int)
    candidate = discrete_metrics(observed, probabilities, support)
    baseline = discrete_metrics(
        observed,
        normal_discrete_pmf(
            [mean[element] for element in ids],
            [sd[element] for element in ids],
            support,
        ),
        support,
    )

    def rounded(payload: dict) -> dict:
        return {
            key: (round(float(value), 7) if isinstance(value, (float, np.floating)) else value)
            for key, value in payload.items()
        }

    return {
        "artifact_sha256": distribution.get("artifact_sha256"),
        "candidate": rounded(candidate),
        "discretized_normal": rounded(baseline),
        "crps_delta_vs_normal": round(
            candidate["crps_discrete"] - baseline["crps_discrete"], 7
        ),
    }


def _roster(players: list[dict]) -> dict[int, dict]:
    return {
        int(row["element"]): {
            "position": Position.parse(row["element_type"]),
            "team": str(row.get("team_id", "")),
            "price": float(row.get("now_cost") or 0.0) / 10.0,
        }
        for row in players
        if int(row.get("element_type") or 0) in (1, 2, 3, 4)
    }


def _outcome(decision: Decision, results: pd.DataFrame, rules: dict,
             roster: dict[int, dict]) -> dict:
    scored = score_decision(decision, results, rules, roster)
    return {
        "fingerprint": decision.fingerprint(),
        "expected_points": decision.expected_points,
        "actual_points": scored.points,
        "points_before_hits": scored.points_before_hits,
        "hits": scored.hits,
        "captain": decision.captain,
        "captain_points": scored.captain_points,
        "effective_captain": scored.effective_captain,
        "auto_subs": [list(item) for item in scored.auto_subs],
        "players_played": scored.players_played,
    }


def settle_strategy_shadow(shadow: dict, *, season: str, gw: int,
                           live: list[dict], players: list[dict],
                           envelope_id: str | None = None,
                           envelope_sha256: str | None = None,
                           manual: dict | None = None) -> dict:
    """Puntúa control y candidato contra una jornada oficial ya asentada.

    Este cálculo es retrospectivo y puro: jamás selecciona ni ejecuta acciones.
    Rechaza un artefacto que no declare explícitamente su falta de autoridad.
    """
    if shadow.get("schema") != "mova-strategy-shadow-v1":
        raise ValueError("strategy shadow incompatible")
    if shadow.get("selected_for_execution") is not False:
        raise ValueError("strategy shadow no está marcado como no ejecutable")
    if shadow.get("virtual_trajectory") is not True:
        raise ValueError("strategy shadow no conserva una trayectoria virtual")
    if shadow.get("chips") != "disabled_in_both_arms":
        raise ValueError("el par de shadow no aisló chips en ambos brazos")
    if (shadow.get("control", {}).get("violations")
            or shadow.get("candidate", {}).get("violations")):
        raise ValueError("el par de shadow contiene decisiones inválidas")

    control = Decision.from_dict(shadow["control"]["decision"])
    candidate = Decision.from_dict(shadow["candidate"]["decision"])
    if {(control.season, control.gw), (candidate.season, candidate.gw)} != {
            (str(season), int(gw))}:
        raise ValueError("decisiones de shadow no corresponden al settlement")
    if control.chip is not None or candidate.chip is not None:
        raise ValueError("el par aislado no puede contener chips")

    results = pd.DataFrame(live)
    _, actual_points = collapse_results(results)
    actual = {int(element): int(points) for element, points in actual_points.items()}
    projections = shadow.get("projections") or {}
    control_xp = _row(projections.get("control_horizon_xp") or {}, gw)
    candidate_xp = _row(projections.get("candidate_horizon_xp") or {}, gw)
    candidate_sd = _row(projections.get("candidate_horizon_sd") or {}, gw)
    rules = get_rules(season).SQUAD
    roster = _roster(players)
    control_outcome = _outcome(control, results, rules, roster)
    candidate_outcome = _outcome(candidate, results, rules, roster)

    candidate_forecast = _forecast_metrics(candidate_xp, actual, candidate_sd)
    discrete = projections.get("candidate_current_distribution")
    if discrete:
        candidate_forecast["discrete"] = _discrete_forecast_metrics(
            discrete, mean=candidate_xp, sd=candidate_sd, actual=actual
        )
    payload = {
        "schema": SCHEMA,
        "experiment_id": shadow.get("experiment_id"),
        "strategy_key": shadow.get("strategy_key"),
        "season": str(season),
        "gw": int(gw),
        "status": "settled",
        "selected_for_execution": False,
        "virtual_trajectory": True,
        "trajectory": dict(shadow.get("trajectory") or {}),
        "envelope_id": envelope_id,
        "envelope_sha256": envelope_sha256,
        "control": {
            "decision": control_outcome,
            "forecast": _forecast_metrics(control_xp, actual),
        },
        "candidate": {
            "decision": candidate_outcome,
            "forecast": candidate_forecast,
        },
        "comparison": {
            "realized_points_delta": (
                candidate_outcome["actual_points"] - control_outcome["actual_points"]
            ),
            "expected_points_delta": round(
                candidate_outcome["expected_points"] - control_outcome["expected_points"],
                2,
            ),
            "squad_changed": set(candidate.squad_15) != set(control.squad_15),
            "lineup_changed": set(candidate.starters) != set(control.starters),
            "captain_changed": candidate.captain != control.captain,
            "candidate_transfers": len(candidate.transfers_in),
            "control_transfers": len(control.transfers_in),
            "candidate_hits": candidate.hits,
            "control_hits": control.hits,
        },
    }
    if manual:
        payload["manual"] = {
            "fingerprint": manual.get("fingerprint"),
            "expected_points": manual.get("expected_points"),
            "actual_points": int(manual["actual_points"]),
            "candidate_realized_delta": (
                candidate_outcome["actual_points"] - int(manual["actual_points"])
            ),
            "control_realized_delta": (
                control_outcome["actual_points"] - int(manual["actual_points"])
            ),
        }
    return payload


def aggregate_strategy_shadow(settlements: list[dict], *, minimum: int = 3) -> dict:
    """Resume la racha más reciente; nunca promueve automáticamente."""
    if minimum < 1:
        raise ValueError("minimum debe ser positivo")
    observations = sorted(
        settlements, key=lambda row: (str(row.get("season")), int(row.get("gw", 0)))
    )
    keys = [
        (str(row.get("season")), int(row.get("gw", 0))) for row in observations
    ]
    if len(keys) != len(set(keys)):
        raise ValueError("settlements duplicados para una misma season/GW")
    trailing: list[dict] = []
    for row in observations:
        if row.get("status") != "settled":
            trailing = []
            continue
        if (trailing
                and row.get("trajectory", {}).get("mode") != "carried_from_previous"):
            trailing = []
        if (trailing and (row["season"] != trailing[-1]["season"]
                          or int(row["gw"]) != int(trailing[-1]["gw"]) + 1)):
            trailing = []
        trailing.append(row)

    checks = {
        "minimum_consecutive_gameweeks": len(trailing) >= minimum,
        "all_non_executable": all(
            row.get("selected_for_execution") is False for row in trailing
        ),
        "stateful_virtual_trajectory": all(
            row.get("virtual_trajectory") is True for row in trailing
        ),
        "same_strategy": len({row.get("strategy_key") for row in trailing}) <= 1,
        "same_experiment": len({row.get("experiment_id") for row in trailing}) <= 1,
        "complete_forecasts": all(
            int(row.get("candidate", {}).get("forecast", {}).get("rows", 0)) > 0
            for row in trailing
        ),
    }
    ready = bool(trailing) and all(checks.values())
    deltas = [int(row["comparison"]["realized_points_delta"]) for row in trailing]
    forecast = _aggregate_forecasts(
        [row["candidate"]["forecast"] for row in trailing]
    ) if trailing else {}
    return {
        "schema": GATE_SCHEMA,
        "status": "review_required" if ready else "insufficient_evidence",
        "promotion_authorized": False,
        "minimum_required": minimum,
        "consecutive_gameweeks": len(trailing),
        "season": trailing[-1]["season"] if trailing else None,
        "gameweeks": [int(row["gw"]) for row in trailing],
        "checks": checks,
        "policy": {
            "candidate_points_delta": sum(deltas),
            "mean_delta": round(float(np.mean(deltas)), 3) if deltas else None,
            "wins": sum(value > 0 for value in deltas),
            "losses": sum(value < 0 for value in deltas),
            "ties": sum(value == 0 for value in deltas),
            "action_changes": sum(bool(row["comparison"]["squad_changed"]
                                       or row["comparison"]["lineup_changed"]
                                       or row["comparison"]["captain_changed"])
                                  for row in trailing),
        },
        "candidate_forecast": forecast,
        "next_action": (
            "socialize_and_request_explicit_human_decision"
            if ready else "collect_more_consecutive_live_deadlines"
        ),
    }


def _aggregate_forecasts(rows: list[dict]) -> dict:
    total = sum(int(row["rows"]) for row in rows)
    if not total:
        return {}

    def weighted(name: str) -> float:
        return sum(float(row[name]) * int(row["rows"]) for row in rows) / total

    valid_spearman = [row for row in rows if row.get("spearman") is not None]
    output = {
        "rows": total,
        "mae": round(weighted("mae"), 7),
        "rmse": round(sqrt(sum(
            float(row["rmse"]) ** 2 * int(row["rows"]) for row in rows
        ) / total), 7),
        "bias": round(weighted("bias"), 7),
        "mean_gameweek_spearman": (
            round(sum(float(row["spearman"]) * int(row["rows"])
                      for row in valid_spearman)
                  / sum(int(row["rows"]) for row in valid_spearman), 7)
            if valid_spearman else None
        ),
    }
    for name in ("crps_normal", "coverage_50", "coverage_80", "coverage_90"):
        if all(name in row for row in rows):
            output[name] = round(weighted(name), 7)
    if all(row.get("discrete") for row in rows):
        discrete_rows = [row["discrete"] for row in rows]
        output["discrete"] = {
            "artifact_sha256": discrete_rows[-1].get("artifact_sha256"),
            "crps_delta_vs_normal": round(sum(
                float(row["crps_delta_vs_normal"]) * int(source["rows"])
                for row, source in zip(discrete_rows, rows)
            ) / total, 7),
        }
        for arm in ("candidate", "discretized_normal"):
            output["discrete"][arm] = {}
            for name in ("crps_discrete", "log_score", "zero_brier",
                         "predicted_zero_rate", "observed_zero_rate",
                         "coverage_50", "coverage_80", "coverage_90"):
                output["discrete"][arm][name] = round(sum(
                    float(row[arm][name]) * int(source["rows"])
                    for row, source in zip(discrete_rows, rows)
                ) / total, 7)
    return output
