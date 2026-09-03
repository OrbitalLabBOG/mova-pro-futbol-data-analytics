"""Reglas FPL 2024/25 necesarias para replay causal sin chips.

Fuente oficial de gol de portero a 10 y cinco FT: premierleague.com/en/news/4058895.
"""
from __future__ import annotations

from mova_fpl.rules.base import Position, ScoringTable
from mova_fpl.rules.bps import BPS_2025_26
from mova_fpl.rules.chips import ChipCatalogue, ChipWindow
from mova_fpl.rules import season_2021_24 as _previous

SEASON = "2024-25"
HISTORICAL_CHIPS_SUPPORTED = False

# En 2024/25 el gol de portero pasó de seis a diez puntos. DefCon aún no existía.
SCORING = ScoringTable(
    goal_points={Position.GKP: 10, Position.DEF: 6, Position.MID: 5, Position.FWD: 4},
    clean_sheet_points={Position.GKP: 4, Position.DEF: 4, Position.MID: 1, Position.FWD: 0},
    defcon_points=0,
    defcon_thresholds={},
)

BPS = BPS_2025_26
SQUAD = {**_previous.SQUAD, "max_free_transfers": 5}
CHIPS = ChipCatalogue(chips=(), windows=(ChipWindow("season", 1, 38),), per_window=0)
