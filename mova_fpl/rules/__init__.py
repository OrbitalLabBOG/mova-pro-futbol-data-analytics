"""Motor de reglas FPL, versionado por temporada. Puro: sin datos, sin I/O."""
from __future__ import annotations

from types import ModuleType

from mova_fpl.rules import season_2021_24, season_2024_25, season_2025_26, season_2026_27
from mova_fpl.rules.base import (PlayerStats, PointsBreakdown, Position, ScoringTable,
                                 Squad, SquadPlayer, Violation)
from mova_fpl.rules.scoring import score as _score

_REGISTRY: dict[str, ModuleType] = {
    "2020-21": season_2021_24,
    "2021-22": season_2021_24,
    "2023-24": season_2021_24,
    "2024-25": season_2024_25,
    "2025-26": season_2025_26,
    "2026-27": season_2026_27,
}


def get(season: str) -> ModuleType:
    """Modulo de reglas de una temporada."""
    try:
        return _REGISTRY[season]
    except KeyError:
        raise ValueError(
            f"no hay reglas para {season}. Disponibles: {sorted(_REGISTRY)}."
        ) from None


def score(stats: PlayerStats, season: str) -> PointsBreakdown:
    return _score(stats, get(season).SCORING)


def seasons() -> list[str]:
    return sorted(_REGISTRY)


__all__ = ["get", "score", "seasons", "PlayerStats", "PointsBreakdown", "Position",
           "ScoringTable", "Squad", "SquadPlayer", "Violation"]
