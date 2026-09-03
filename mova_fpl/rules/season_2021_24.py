"""Reglas históricas comparables de 2020/21, 2021/22 y 2023/24.

2022/23 se excluye del harness principal porque la ventana de transferencias
ilimitadas del Mundial entre GW16 y GW17 exige una transición especial que el
simulador todavía no representa. Los chips históricos tampoco se simulan en
este módulo; los replays deben usar ``chip_policy='none'``.

Fuente de la excepción 2022/23: premierleague.com/en/news/2667633.
"""
from __future__ import annotations

from mova_fpl.rules.base import Position, ScoringTable
from mova_fpl.rules.bps import BPS_2025_26
from mova_fpl.rules.chips import ChipCatalogue, ChipWindow

SEASON = "2020-24-historical"
HISTORICAL_CHIPS_SUPPORTED = False

SCORING = ScoringTable(
    goal_points={Position.GKP: 6, Position.DEF: 6, Position.MID: 5, Position.FWD: 4},
    clean_sheet_points={Position.GKP: 4, Position.DEF: 4, Position.MID: 1, Position.FWD: 0},
    defcon_points=0,
    defcon_thresholds={},
)

# El modelo consume los BPS observados y bonus reales; esta tabla no interviene
# en el score histórico. Se conserva para satisfacer la interfaz versionada.
BPS = BPS_2025_26

SQUAD = dict(
    budget=100.0, size=15, max_per_club=3,
    composition={Position.GKP: 2, Position.DEF: 5, Position.MID: 5, Position.FWD: 3},
    starters=11,
    formation_min={Position.GKP: 1, Position.DEF: 3, Position.MID: 2, Position.FWD: 1},
    formation_max={Position.GKP: 1, Position.DEF: 5, Position.MID: 5, Position.FWD: 3},
    max_free_transfers=2, hit_cost=4, captain_multiplier=2,
)

CHIPS = ChipCatalogue(chips=(), windows=(ChipWindow("season", 1, 38),), per_window=0)
