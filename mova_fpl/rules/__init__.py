"""Motor de reglas FPL, versionado por temporada. Puro: sin datos, sin I/O."""
from __future__ import annotations

from types import ModuleType

from mova_fpl.rules import season_2025_26, season_2026_27
from mova_fpl.rules.base import (PlayerStats, PointsBreakdown, Position, ScoringTable,
                                 Squad, SquadPlayer, Violation)
from mova_fpl.rules.scoring import score as _score

_REGISTRY: dict[str, ModuleType] = {
    "2025-26": season_2025_26,
    "2026-27": season_2026_27,
}


def get(season: str) -> ModuleType:
    """Modulo de reglas de una temporada."""
    try:
        return _REGISTRY[season]
    except KeyError:
        raise ValueError(
            f"no hay reglas para {season}. Disponibles: {sorted(_REGISTRY)}. "
            "Las temporadas anteriores a 2025/26 no se modelan: no tienen "
            "contribucion defensiva y no son el juego que se va a jugar."
        ) from None


def score(stats: PlayerStats, season: str) -> PointsBreakdown:
    return _score(stats, get(season).SCORING)


def seasons() -> list[str]:
    return sorted(_REGISTRY)


__all__ = ["get", "score", "seasons", "PlayerStats", "PointsBreakdown", "Position",
           "ScoringTable", "Squad", "SquadPlayer", "Violation"]
