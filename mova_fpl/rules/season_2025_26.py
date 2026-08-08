"""Reglas FPL 2025/26. Primera temporada con contribucion defensiva."""
from __future__ import annotations

from mova_fpl.rules.base import Position, ScoringTable
from mova_fpl.rules.bps import BPS_2025_26

SEASON = "2025-26"

SCORING = ScoringTable(
    goal_points={Position.GKP: 6, Position.DEF: 6, Position.MID: 5, Position.FWD: 4},
    clean_sheet_points={Position.GKP: 4, Position.DEF: 4, Position.MID: 1, Position.FWD: 0},
    defcon_points=2,
    # GKP no es elegible para contribucion defensiva
    defcon_thresholds={Position.DEF: 10, Position.MID: 12, Position.FWD: 12},
)

BPS = BPS_2025_26

SQUAD = dict(
    budget=100.0, size=15, max_per_club=3,
    composition={Position.GKP: 2, Position.DEF: 5, Position.MID: 5, Position.FWD: 3},
    starters=11,
    formation_min={Position.GKP: 1, Position.DEF: 3, Position.MID: 2, Position.FWD: 1},
    formation_max={Position.GKP: 1, Position.DEF: 5, Position.MID: 5, Position.FWD: 3},
    max_free_transfers=5, hit_cost=4, captain_multiplier=2,
)

CHIPS = ("wildcard", "free_hit", "bench_boost", "triple_captain")
