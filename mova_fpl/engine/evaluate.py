"""Puntuacion de una decision contra los resultados reales de la jornada."""
from __future__ import annotations

import pandas as pd

from mova_fpl.engine.state import Decision, GwOutcome
from mova_fpl.rules.autosubs import apply_auto_subs, effective_captain
from mova_fpl.rules.base import Position, Squad, SquadPlayer
from mova_fpl.rules.chips import effect


def collapse_results(results: pd.DataFrame) -> tuple[dict, dict]:
    """Minutos y puntos por elemento, SUMANDO los partidos de una doble jornada."""
    if results.empty:
        return {}, {}
    agg = results.groupby("element").agg(minutes=("minutes", "sum"),
                                         points=("total_points", "sum"))
    return agg["minutes"].to_dict(), agg["points"].to_dict()


def score_decision(decision: Decision, results: pd.DataFrame, rules: dict,
                   roster: dict | None = None) -> GwOutcome:
    """Puntos reales obtenidos por una decision.

    Aplica sustituciones automaticas, capitan efectivo y el efecto del chip.
    Los jugadores sin fila en la jornada puntuan 0 (no jugaron).
    """
    minutos, puntos = collapse_results(results)
    ef = effect(decision.chip)

    roster = roster or {}
    players = tuple(
        SquadPlayer(element=e,
                    position=roster.get(e, {}).get("position", Position.MID),
                    team=roster.get(e, {}).get("team", ""),
                    price=roster.get(e, {}).get("price", 0.0))
        for e in decision.squad_15
    )
    squad = Squad(players=players, starters=decision.starters,
                  captain=decision.captain, vice_captain=decision.vice_captain,
                  bench_order=decision.bench_order)

    if ef.scoring_players == "squad":            # bench boost: puntua la plantilla entera
        xi, subs = list(decision.squad_15), []
    else:
        xi, subs = apply_auto_subs(squad, minutos, rules)

    cap = effective_captain(squad, minutos)
    base = sum(int(puntos.get(e, 0)) for e in xi)
    extra_cap = int(puntos.get(cap, 0)) * (ef.captain_multiplier - 1) if cap is not None else 0

    bruto = base + extra_cap
    return GwOutcome(
        gw=decision.gw,
        points=bruto - decision.hits * int(rules["hit_cost"]),
        points_before_hits=bruto,
        hits=decision.hits,
        captain_points=int(puntos.get(cap, 0)) if cap is not None else 0,
        auto_subs=tuple(subs),
        effective_captain=cap,
        players_played=sum(1 for e in xi if int(minutos.get(e, 0)) > 0),
    )
