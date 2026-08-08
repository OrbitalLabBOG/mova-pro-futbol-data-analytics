"""Efecto de los chips sobre la puntuacion. Puro.

v1 implementa el EFECTO de cada chip y su disponibilidad. La POLITICA de cuando
usarlos queda fuera de alcance (Q-04): la decide una heuristica simple.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChipEffect:
    scoring_players: str      # "xi" o "squad"
    captain_multiplier: int
    free_squad: bool          # plantilla libre sin coste de transferencias
    reverts_after_gw: bool    # la plantilla vuelve al estado previo


EFFECTS = {
    None:              ChipEffect("xi",    2, False, False),
    "wildcard":        ChipEffect("xi",    2, True,  False),
    "free_hit":        ChipEffect("xi",    2, True,  True),
    "bench_boost":     ChipEffect("squad", 2, False, False),
    "triple_captain":  ChipEffect("xi",    3, False, False),
}


def effect(chip: str | None) -> ChipEffect:
    if chip not in EFFECTS:
        raise ValueError(f"chip desconocido: {chip!r}. Validos: {sorted(k for k in EFFECTS if k)}")
    return EFFECTS[chip]


def available(used: set[str] | frozenset[str], catalogue: tuple[str, ...]) -> list[str]:
    return [c for c in catalogue if c not in (used or set())]
