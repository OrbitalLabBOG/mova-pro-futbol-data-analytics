"""Tabla de pesos del Bonus Points System, versionada por temporada.

No se recalcula BPS de punta a punta: requiere ~30 componentes por jugador que
las fuentes publicas no exponen (I-03 del brief). Lo que si se versiona es la
TABLA de pesos, porque (a) documenta con precision que cambio entre temporadas
y (b) alimenta el modelo de bonus esperado en WP-005.

Fuente 2026/27: premierleague.com/news/4679946 y /news/4679873
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BpsTable:
    season: str
    #: cuantas acciones CBI hacen falta para sumar 1 BPS
    cbi_per_bps: int
    #: BPS por atajada dentro del area
    save_in_box: int
    #: BPS por atajada fuera del area; None = la metrica no existe esa temporada
    save_out_box: int | None
    #: BPS extra por atajar una ocasion clara
    save_big_chance: int
    #: BPS por atajar un penalti
    penalty_save: int

    def diff(self, other: "BpsTable") -> list[str]:
        out = []
        for f in ("cbi_per_bps", "save_in_box", "save_out_box", "save_big_chance", "penalty_save"):
            a, b = getattr(self, f), getattr(other, f)
            if a != b:
                out.append(f"{f}: {a} -> {b}")
        return out


# Temporada 2025/26: primera con contribucion defensiva.
BPS_2025_26 = BpsTable(
    season="2025-26",
    cbi_per_bps=2,
    save_in_box=1,
    save_out_box=1,
    save_big_chance=0,
    penalty_save=8,
)

# Temporada 2026/27: reforma del BPS para reducir el solape con DefCon y
# mejorar a porteros, laterales y atacantes.
BPS_2026_27 = BpsTable(
    season="2026-27",
    cbi_per_bps=3,        # antes 1 BPS por cada 2 CBI
    save_in_box=1,
    save_out_box=None,    # metrica eliminada
    save_big_chance=1,    # metrica nueva
    penalty_save=7,       # antes 8
)

#: Los cuatro cambios de 2025/26 a 2026/27, segun la fuente oficial.
#: El diff calculado debe coincidir exactamente con esta lista (AC-WP002-005).
CAMBIOS_2026_27 = [
    "cbi_per_bps: 2 -> 3",        # 1 BPS por cada 3 CBI, antes por cada 2
    "save_out_box: 1 -> None",    # metrica eliminada
    "save_big_chance: 0 -> 1",    # metrica nueva
    "penalty_save: 8 -> 7",
]
