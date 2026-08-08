"""Sustituciones automaticas. Puro.

FPL sustituye a un titular que jugo 0 minutos por el primer suplente del orden
de banca que mantenga una formacion valida. El portero suplente solo puede
entrar por el portero titular.
"""
from __future__ import annotations

from mova_fpl.rules.base import Position, Squad
from mova_fpl.rules.squad import is_valid_formation


def apply_auto_subs(squad: Squad, minutes: dict[int, int], rules: dict) -> tuple[list[int], list[tuple[int, int]]]:
    """Devuelve (XI efectivo, sustituciones aplicadas como (sale, entra))."""
    by_id = {p.element: p for p in squad.players}
    xi = list(squad.starters)
    bench = list(squad.bench_order) or [p.element for p in squad.players if p.element not in xi]
    played = lambda e: int(minutes.get(e, 0)) > 0            # noqa: E731

    subs: list[tuple[int, int]] = []

    # 1) portero: intercambio directo, sin condicion de formacion
    gk_xi = [e for e in xi if by_id[e].position is Position.GKP]
    for gk in gk_xi:
        if played(gk):
            continue
        gk_bench = [e for e in bench if by_id[e].position is Position.GKP and played(e)]
        if gk_bench:
            entra = gk_bench[0]
            xi[xi.index(gk)] = entra
            bench.remove(entra)
            subs.append((gk, entra))

    # 2) jugadores de campo, en orden de banca, respetando formacion valida
    for sale in [e for e in list(xi) if by_id[e].position is not Position.GKP and not played(e)]:
        for entra in list(bench):
            if by_id[entra].position is Position.GKP or not played(entra):
                continue
            tentativa = [by_id[x].position for x in xi]
            tentativa[xi.index(sale)] = by_id[entra].position
            if is_valid_formation(tentativa, rules):
                xi[xi.index(sale)] = entra
                bench.remove(entra)
                subs.append((sale, entra))
                break

    return xi, subs


def effective_captain(squad: Squad, minutes: dict[int, int]) -> int | None:
    """El vice asume el multiplicador solo si el capitan jugo 0 minutos."""
    if squad.captain is not None and int(minutes.get(squad.captain, 0)) > 0:
        return squad.captain
    if squad.vice_captain is not None and int(minutes.get(squad.vice_captain, 0)) > 0:
        return squad.vice_captain
    return squad.captain
