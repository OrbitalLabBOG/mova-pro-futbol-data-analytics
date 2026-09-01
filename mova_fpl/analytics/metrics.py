"""Métricas puras para reconciliar una predicción contra una gameweek cerrada."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from mova_fpl.models.minutes import expected_calibration_error
from mova_fpl.models.points import COMPONENTES as COMPONENTS
from mova_fpl.rules.base import Position


def _safe_float(value, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _corr(left: pd.Series, right: pd.Series, *, method: str) -> float | None:
    if len(left) < 3 or left.nunique() < 2 or right.nunique() < 2:
        return None
    value = left.corr(right, method=method)
    return None if pd.isna(value) else float(value)


def _brier(y, p) -> float | None:
    yy, pp = np.asarray(y, dtype=float), np.clip(np.asarray(p, dtype=float), 0, 1)
    return float(np.mean((yy - pp) ** 2)) if len(yy) else None


def _log_loss(y, p) -> float | None:
    yy, pp = np.asarray(y, dtype=float), np.clip(np.asarray(p, dtype=float), 1e-9, 1 - 1e-9)
    return float(-np.mean(yy * np.log(pp) + (1 - yy) * np.log(1 - pp))) if len(yy) else None


def actual_components(actual: pd.DataFrame, scoring) -> pd.DataFrame:
    """Convierte `stats` del endpoint oficial a los componentes auditables de xP."""
    rows = []
    for row in actual.to_dict("records"):
        stats = row.get("stats") or {}
        position = Position.parse(row["position"])
        minutes = _safe_float(stats.get("minutes", row.get("minutes")))
        defensive = _safe_float(stats.get("defensive_contribution"))
        threshold = scoring.defcon_thresholds.get(position, 0)
        behind = position in {Position.GKP, Position.DEF}
        values = {
            "pts_aparicion": (scoring.appearance_long if minutes >= scoring.minutes_for_long
                               else scoring.appearance_short if minutes > 0 else 0),
            "pts_goles": _safe_float(stats.get("goals_scored")) *
                          scoring.goal_points.get(position, 4),
            "pts_asistencias": _safe_float(stats.get("assists")) * scoring.assist_points,
            "pts_cs": _safe_float(stats.get("clean_sheets")) *
                      scoring.clean_sheet_points.get(position, 0),
            "pts_encajados": -math.floor(_safe_float(stats.get("goals_conceded")) / 2)
                              if behind else 0,
            "pts_defcon": scoring.defcon_points if threshold and defensive >= threshold else 0,
            "pts_bonus": _safe_float(stats.get("bonus")),
            "pts_tarjetas": (_safe_float(stats.get("yellow_cards")) * scoring.yellow_card_points
                              + _safe_float(stats.get("red_cards")) * scoring.red_card_points),
            "pts_paradas": math.floor(_safe_float(stats.get("saves")) /
                                      scoring.saves_per_point),
            "pts_otros": (_safe_float(stats.get("penalties_saved")) *
                           scoring.penalty_save_points + _safe_float(stats.get("penalties_missed")) *
                           scoring.penalty_miss_points + _safe_float(stats.get("own_goals")) *
                           scoring.own_goal_points),
        }
        rows.append({"element": int(row["element"]), "minutes_real": minutes,
                     "total_real": _safe_float(stats.get("total_points", row.get("total_points"))),
                     "clean_sheet_real": float(bool(_safe_float(stats.get("clean_sheets")))),
                     **values})
    return pd.DataFrame(rows)


def evaluate_gameweek(predictions: pd.DataFrame, actual: pd.DataFrame, scoring) -> dict:
    """Devuelve scorecard JSON y tabla de componentes sin tocar almacenamiento."""
    required = {"element", "xp", "p_play", "p_60", "position", "components"}
    missing = required - set(predictions)
    if missing:
        raise ValueError(f"proyecciones incompletas: faltan {sorted(missing)}")
    if predictions["element"].duplicated().any():
        raise ValueError("proyecciones duplicadas por element")

    expanded = predictions.copy()
    for component in COMPONENTS:
        expanded[f"{component}_pred"] = expanded["components"].map(
            lambda value: _safe_float((value or {}).get(component))
        )
    matched_players = len(set(predictions["element"]) & set(actual.get("element", [])))
    joined_actual = actual.merge(predictions[["element", "position"]], on="element", how="right")
    realized = actual_components(joined_actual, scoring)
    frame = expanded.merge(realized, on="element", how="left")
    actual_columns = ["minutes_real", "total_real", "clean_sheet_real", *COMPONENTS]
    frame[actual_columns] = frame[actual_columns].fillna(0.0)

    error = frame["xp"].astype(float) - frame["total_real"]
    predicted_total = float(frame["xp"].sum())
    actual_total = float(frame["total_real"].sum())
    play_y = (frame["minutes_real"] > 0).astype(float)
    sixty_y = (frame["minutes_real"] >= scoring.minutes_for_long).astype(float)
    p_play = frame["p_play"].astype(float).clip(0, 1)
    p_60 = frame["p_60"].astype(float).clip(0, 1)

    eligible = frame["position"].isin(["GKP", "GK", "DEF"])
    cs_y = frame.loc[eligible, "clean_sheet_real"]
    # El modelo no expone una columna CS explícita; para GKP/DEF, pts_cs / puntos
    # de CS es la probabilidad marginal incluyendo minutos. Condicionar por P60
    # evita evaluar dos veces la disponibilidad.
    cs_points = frame.loc[eligible, "position"].map(
        lambda pos: scoring.clean_sheet_points.get(Position.parse(pos), 0)
    ).astype(float)
    fallback = (frame.loc[eligible, "pts_cs_pred"] / cs_points.replace(0, np.nan)).fillna(0)
    contexts = (frame["context"] if "context" in frame else pd.Series(
        [{} for _ in range(len(frame))], index=frame.index, dtype=object
    ))
    p_cs = contexts.loc[eligible].map(
        lambda value: (value or {}).get("p_clean_sheet_award")
    ).astype(float).fillna(fallback).clip(0, 1)

    components = []
    for component in COMPONENTS:
        pred = frame[f"{component}_pred"].astype(float)
        real = frame[component].astype(float)
        actual_sum = float(real.sum())
        bias = float((pred - real).sum())
        components.append({
            "component": component, "predicted_total": float(pred.sum()),
            "actual_total": actual_sum, "bias": bias,
            "relative_bias": bias / abs(actual_sum) if actual_sum else None,
            "mae": float((pred - real).abs().mean()),
        })

    predicted_component_total = frame[[f"{name}_pred" for name in COMPONENTS]].sum(axis=1)
    actual_component_total = frame[list(COMPONENTS)].sum(axis=1)
    predicted_residual = predicted_component_total - frame["xp"]
    actual_residual = actual_component_total - frame["total_real"]

    metrics = {
        "schema": "mova-model-scorecard-v1",
        "sample_size": int(len(frame)),
        "coverage": {
            "projected_players": int(len(predictions)),
            "actual_players": int(actual["element"].nunique()) if not actual.empty else 0,
            "matched_players": int(matched_players),
        },
        "points": {
            "predicted_total": predicted_total, "actual_total": actual_total,
            "bias": predicted_total - actual_total,
            "relative_bias": ((predicted_total - actual_total) / abs(actual_total)
                              if actual_total else None),
            "mae": float(error.abs().mean()), "rmse": float(np.sqrt(np.mean(error ** 2))),
            "pearson": _corr(frame["xp"], frame["total_real"], method="pearson"),
            "spearman": _corr(frame["xp"], frame["total_real"], method="spearman"),
        },
        "minutes": {
            "play_brier": _brier(play_y, p_play),
            "play_ece": float(expected_calibration_error(play_y, p_play)),
            "p60_brier": _brier(sixty_y, p_60),
            "p60_ece": float(expected_calibration_error(sixty_y, p_60)),
        },
        "clean_sheet": {
            "sample_size": int(eligible.sum()), "brier": _brier(cs_y, p_cs),
            "log_loss": _log_loss(cs_y, p_cs),
        },
        "accounting": {
            "predicted_residual_max_abs": float(predicted_residual.abs().max()),
            "actual_residual_max_abs": float(actual_residual.abs().max()),
            "actual_residual_rows": int((actual_residual.abs() > 1e-9).sum()),
        },
        "components": components,
    }
    return {"metrics": metrics, "components": components, "frame": frame}
