"""Restricciones de plantilla y alineacion. Puro."""
from __future__ import annotations

from collections import Counter

from mova_fpl.rules.base import Position, Squad, Violation


def validate_squad(squad: Squad, rules: dict, *, check_budget: bool = True) -> list[Violation]:
    """Lista de violaciones. Vacia significa plantilla valida.

    Devuelve TODAS las violaciones, no la primera: al depurar un optimizador
    infactible hace falta el cuadro completo.
    """
    v: list[Violation] = []
    players = squad.players
    by_id = {p.element: p for p in players}

    if len(players) != rules["size"]:
        v.append(Violation("SQUAD_SIZE", f"{len(players)} jugadores, se esperaban {rules['size']}"))
    if len(by_id) != len(players):
        dup = [e for e, c in Counter(p.element for p in players).items() if c > 1]
        v.append(Violation("DUPLICATE_PLAYER", f"elementos repetidos: {dup}"))

    counts = Counter(p.position for p in players)
    for pos, expected in rules["composition"].items():
        if counts.get(pos, 0) != expected:
            v.append(Violation("COMPOSITION",
                               f"{pos.value}: {counts.get(pos, 0)}, se esperaban {expected}"))

    clubs = Counter(p.team for p in players if p.team)
    for club, n in clubs.items():
        if n > rules["max_per_club"]:
            v.append(Violation("MAX_PER_CLUB", f"{club}: {n} jugadores (maximo {rules['max_per_club']})"))

    if check_budget:
        cost = round(sum(p.price for p in players), 1)
        limit = round(rules["budget"] + squad.bank, 1)
        if cost > limit + 1e-9:
            v.append(Violation("BUDGET", f"coste {cost}M supera {limit}M"))

    if squad.starters:
        v += _validate_lineup(squad, rules, by_id)
    return v


def _validate_lineup(squad: Squad, rules: dict, by_id: dict) -> list[Violation]:
    v: list[Violation] = []
    starters = squad.starters

    if len(starters) != rules["starters"]:
        v.append(Violation("STARTERS_COUNT", f"{len(starters)} titulares, se esperaban {rules['starters']}"))
    unknown = [e for e in starters if e not in by_id]
    if unknown:
        v.append(Violation("STARTER_NOT_IN_SQUAD", f"titulares fuera de la plantilla: {unknown}"))

    line = Counter(by_id[e].position for e in starters if e in by_id)
    for pos, lo in rules["formation_min"].items():
        if line.get(pos, 0) < lo:
            v.append(Violation("FORMATION_MIN", f"{pos.value}: {line.get(pos, 0)} < minimo {lo}"))
    for pos, hi in rules["formation_max"].items():
        if line.get(pos, 0) > hi:
            v.append(Violation("FORMATION_MAX", f"{pos.value}: {line.get(pos, 0)} > maximo {hi}"))

    if squad.captain is None:
        v.append(Violation("NO_CAPTAIN", "no se designo capitan"))
    elif squad.captain not in starters:
        v.append(Violation("CAPTAIN_NOT_STARTING", f"el capitan {squad.captain} no esta en el XI"))
    if squad.vice_captain is None:
        v.append(Violation("NO_VICE_CAPTAIN", "no se designo vicecapitan"))
    elif squad.vice_captain not in starters:
        v.append(Violation("VICE_NOT_STARTING", f"el vice {squad.vice_captain} no esta en el XI"))
    if squad.captain is not None and squad.captain == squad.vice_captain:
        v.append(Violation("CAPTAIN_IS_VICE", "capitan y vice son el mismo jugador"))
    return v


def is_valid_formation(positions, rules: dict) -> bool:
    line = Counter(positions)
    if sum(line.values()) != rules["starters"]:
        return False
    return all(rules["formation_min"].get(p, 0) <= line.get(p, 0) <= rules["formation_max"].get(p, 99)
               for p in (Position.GKP, Position.DEF, Position.MID, Position.FWD))
