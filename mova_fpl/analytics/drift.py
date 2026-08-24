"""Política conservadora de drift: alerta sólo con una referencia suficiente."""

from __future__ import annotations

import statistics


def _median(references: list[dict], section: str, metric: str):
    values = [item.get(section, {}).get(metric) for item in references]
    clean = [float(value) for value in values if value is not None]
    return statistics.median(clean) if clean else None


def assess_drift(metrics: dict, references: list[dict], *, min_reference: int = 6) -> dict:
    """Compara una GW con la mediana de GWs previas del mismo modelo/variante."""
    result = {"schema": "mova-model-drift-v1", "reference_gameweeks": len(references),
              "minimum_reference_gameweeks": min_reference, "reasons": [], "baseline": {}}
    accounting = metrics.get("accounting") or {}
    if accounting.get("actual_residual_rows", 0):
        result["reasons"].append({
            "code": "component_accounting_mismatch", "severity": "alert",
            "value": accounting["actual_residual_rows"], "alert_threshold": 0,
        })
        return {**result, "status": "alert"}
    if len(references) < min_reference:
        return {**result, "status": "insufficient"}

    points = metrics["points"]
    minutes = metrics["minutes"]
    cs = metrics["clean_sheet"]
    baseline = {
        "mae": _median(references, "points", "mae"),
        "rmse": _median(references, "points", "rmse"),
        "spearman": _median(references, "points", "spearman"),
    }
    result["baseline"] = baseline
    severities = []

    def flag(code: str, value, watch: float, alert: float, *, lower_bad: bool = False):
        if value is None:
            return
        if lower_bad:
            severity = "alert" if value < alert else "watch" if value < watch else None
        else:
            severity = "alert" if value > alert else "watch" if value > watch else None
        if severity:
            severities.append(severity)
            result["reasons"].append({"code": code, "severity": severity, "value": value,
                                      "watch_threshold": watch, "alert_threshold": alert})

    flag("absolute_relative_bias", abs(points.get("relative_bias") or 0), .10, .20)
    flag("play_ece", minutes.get("play_ece"), .05, .08)
    flag("p60_ece", minutes.get("p60_ece"), .06, .10)
    flag("clean_sheet_brier", cs.get("brier"), .20, .24)
    if baseline["mae"]:
        flag("mae_deterioration", points["mae"] / baseline["mae"] - 1, .15, .30)
    if baseline["rmse"]:
        flag("rmse_deterioration", points["rmse"] / baseline["rmse"] - 1, .15, .30)
    if baseline["spearman"] is not None and points.get("spearman") is not None:
        drop = baseline["spearman"] - points["spearman"]
        flag("spearman_drop", drop, .10, .20)

    status = "alert" if "alert" in severities else "watch" if severities else "healthy"
    return {**result, "status": status}
