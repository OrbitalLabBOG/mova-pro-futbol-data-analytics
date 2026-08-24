"""Scorecards reproducibles y detección de drift del modelo FPL."""

from mova_fpl.analytics.metrics import COMPONENTS, evaluate_gameweek
from mova_fpl.analytics.drift import assess_drift
from mova_fpl.analytics.projection import project_snapshot, projection_signature
from mova_fpl.rules import get as get_rules


def evaluate_gameweek_for_season(predictions, actual, season: str):
    return evaluate_gameweek(predictions, actual, get_rules(season).SCORING)


__all__ = ["COMPONENTS", "evaluate_gameweek", "evaluate_gameweek_for_season",
           "assess_drift", "project_snapshot", "projection_signature"]
