"""Chips: efecto, inventario y ventanas de caducidad. Puro.

Reforma 2025/26, vigente tambien en 2026/27
-------------------------------------------
Ya no hay un chip de cada tipo por temporada: hay DOS JUEGOS COMPLETOS, uno por
mitad. El primero caduca en el deadline de la GW19 y no se arrastra.

La consecuencia estrategica no es menor: un chip sin usar al cerrar su ventana es
valor quemado. "Guardarlo por si acaso" dejo de ser una opcion defendible, y el
planificador tiene que tratar la caducidad como una fecha limite dura.

Este modulo describe QUE es legal. Cuando conviene usarlos lo decide
`engine/planner.py`; el optimizador decide como aprovecharlos.
"""
from __future__ import annotations

from dataclasses import dataclass

from mova_fpl.rules.base import Violation


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

CHIP_NAMES = tuple(k for k in EFFECTS if k)


@dataclass(frozen=True, slots=True)
class ChipUse:
    """Un chip ya gastado. La jornada importa: define a que ventana se imputa."""
    gw: int
    chip: str


@dataclass(frozen=True, slots=True)
class ChipWindow:
    """Mitad de temporada con su propio juego de chips."""
    name: str
    first_gw: int
    last_gw: int              # inclusive: ultima jornada en que el chip es jugable

    def contains(self, gw: int) -> bool:
        return self.first_gw <= gw <= self.last_gw

    def remaining(self, gw: int) -> int:
        """Jornadas que quedan para usar el chip, contando la actual."""
        return max(0, self.last_gw - gw + 1)


@dataclass(frozen=True, slots=True)
class ChipCatalogue:
    """Que chips existen, cuantos de cada uno y en que ventanas."""
    chips: tuple[str, ...]
    windows: tuple[ChipWindow, ...]
    per_window: int = 1
    unavailable: tuple[tuple[str, tuple[int, ...]], ...] = ()

    def window_for(self, gw: int) -> ChipWindow | None:
        return next((w for w in self.windows if w.contains(gw)), None)

    def total(self) -> int:
        return len(self.chips) * len(self.windows) * self.per_window

    def unavailable_gws(self, chip: str) -> frozenset[int]:
        return frozenset(gw for name, gws in self.unavailable if name == chip for gw in gws)


def effect(chip: str | None) -> ChipEffect:
    if chip not in EFFECTS:
        raise ValueError(f"chip desconocido: {chip!r}. Validos: {sorted(CHIP_NAMES)}")
    return EFFECTS[chip]


def used_in_window(chips_used, window: ChipWindow) -> dict[str, int]:
    """Cuantas veces se gasto cada chip dentro de una ventana."""
    out: dict[str, int] = {}
    for u in chips_used or ():
        if window.contains(u.gw):
            out[u.chip] = out.get(u.chip, 0) + 1
    return out


def available(gw: int, chips_used, catalogue: ChipCatalogue) -> frozenset[str]:
    """Chips que TODAVIA se pueden jugar en esta jornada.

    Vacio si la jornada cae fuera de toda ventana o si ya se gasto un chip en ella.
    """
    ventana = catalogue.window_for(gw)
    if ventana is None:
        return frozenset()
    if any(u.gw == gw for u in chips_used or ()):
        return frozenset()                       # solo un chip por jornada
    gastados = used_in_window(chips_used, ventana)
    return frozenset(c for c in catalogue.chips
                     if gastados.get(c, 0) < catalogue.per_window
                     and gw not in catalogue.unavailable_gws(c)
                     and not (c == "free_hit" and any(
                         u.chip == "free_hit" and u.gw == gw - 1 for u in chips_used or ()
                     )))


def validate_chip(chip: str | None, gw: int, chips_used, catalogue: ChipCatalogue) -> list[Violation]:
    """Violaciones de legalidad al jugar `chip` en `gw`. Vacia = jugada legal.

    Devuelve TODAS las violaciones, no la primera, por la misma razon que
    `validate_squad`: al depurar hace falta el cuadro completo.
    """
    v: list[Violation] = []
    if chip is None:
        return v
    if chip not in catalogue.chips:
        v.append(Violation("CHIP_UNKNOWN", f"{chip!r} no esta en el catalogo de la temporada"))
        return v

    ventana = catalogue.window_for(gw)
    if ventana is None:
        v.append(Violation("CHIP_OUT_OF_WINDOW", f"la GW{gw} no cae en ninguna ventana de chips"))
        return v

    if gw in catalogue.unavailable_gws(chip):
        v.append(Violation("CHIP_UNAVAILABLE_GW",
                           f"{chip} no está disponible en la GW{gw}"))

    if chip == "free_hit" and any(
        u.chip == "free_hit" and u.gw == gw - 1 for u in chips_used or ()
    ):
        v.append(Violation("FREE_HIT_CONSECUTIVE",
                           "el Free Hit no se puede jugar en jornadas consecutivas"))

    if any(u.gw == gw for u in chips_used or ()):
        ya = next(u.chip for u in chips_used if u.gw == gw)
        v.append(Violation("CHIP_ALREADY_PLAYED_THIS_GW",
                           f"en la GW{gw} ya se jugo {ya}: solo se permite un chip por jornada"))

    gastados = used_in_window(chips_used, ventana).get(chip, 0)
    if gastados >= catalogue.per_window:
        v.append(Violation("CHIP_EXHAUSTED",
                           f"{chip} ya se gasto {gastados} vez/veces en la ventana "
                           f"{ventana.name} (GW{ventana.first_gw}-{ventana.last_gw})"))
    return v


def expiring(gw: int, chips_used, catalogue: ChipCatalogue) -> frozenset[str]:
    """Chips que caducan al cerrar esta jornada si no se juegan ahora.

    Es la senal que impide que un chip se pierda: en la ultima jornada de la
    ventana, cualquier valor positivo justifica jugarlo.
    """
    ventana = catalogue.window_for(gw)
    if ventana is None or ventana.last_gw != gw:
        return frozenset()
    return available(gw, chips_used, catalogue)


def wasted(chips_used, catalogue: ChipCatalogue, through_gw: int) -> list[tuple[str, str]]:
    """Chips que caducaron sin usarse hasta `through_gw`. Auditoria del backtest."""
    out: list[tuple[str, str]] = []
    for w in catalogue.windows:
        if w.last_gw > through_gw:
            continue
        gastados = used_in_window(chips_used, w)
        for c in catalogue.chips:
            for _ in range(catalogue.per_window - gastados.get(c, 0)):
                out.append((w.name, c))
    return out
