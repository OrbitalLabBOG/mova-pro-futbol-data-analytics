"""Reglas FPL 2026/27.

Diferencia con 2025/26: la reforma del BPS. La tabla de puntuacion base y los
umbrales de contribucion defensiva NO cambiaron.

Riesgo declarado R-02: esta version no es validable contra ground truth porque
la temporada aun no ocurre. Se valida por diff explicito contra 2025/26 y por
revision contra la fuente oficial.
"""
from __future__ import annotations

from mova_fpl.rules.base import Position, ScoringTable
from mova_fpl.rules.bps import BPS_2026_27
from mova_fpl.rules import season_2025_26 as _prev

SEASON = "2026-27"

# La matriz de puntuacion por accion es identica a 2025/26.
SCORING = ScoringTable(
    goal_points={Position.GKP: 6, Position.DEF: 6, Position.MID: 5, Position.FWD: 4},
    clean_sheet_points={Position.GKP: 4, Position.DEF: 4, Position.MID: 1, Position.FWD: 0},
    defcon_points=2,
    defcon_thresholds={Position.DEF: 10, Position.MID: 12, Position.FWD: 12},
)

BPS = BPS_2026_27

SQUAD = dict(_prev.SQUAD)

CHIPS = _prev.CHIPS
