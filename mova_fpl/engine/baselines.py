"""Baselines obligatorios (REQ-F-009).

Sin ellos un puntaje no significa nada: fue exactamente el error de los reportes
anteriores del proyecto, que celebraban cifras sin nada contra que compararlas.

Los tres se calculan sobre la MISMA temporada y las MISMAS reglas que el motor.
"""
from __future__ import annotations

import random
from collections import Counter

import pandas as pd

from mova_fpl.engine.greedy import SquadInfeasible, as_items, build_squad
from mova_fpl.rules.base import Position


def _armar(pool: pd.DataFrame, rules: dict, orden: str, budget: float) -> list[dict]:
    """Selecciona 15 por `orden` descendente. Delega en el constructor compartido."""
    filas = pool.to_dict("records")
    try:
        ids = build_squad(as_items(filas, "element", "position", "team", "price", orden),
                          rules, budget)
    except SquadInfeasible:
        return []
    por_id = {int(r["element"]): r for r in filas}
    return [por_id[i] for i in ids]


def _mejor_xi(squad: list[dict], rules: dict, key: str) -> list[dict]:
    por_pos = {p: sorted([c for c in squad if c["position"] is p], key=lambda c: -c[key]) for p in Position}
    mejor = None
    lo, hi = rules["formation_min"], rules["formation_max"]
    for nd in range(lo[Position.DEF], hi[Position.DEF] + 1):
        for nm in range(lo[Position.MID], hi[Position.MID] + 1):
            nf = rules["starters"] - 1 - nd - nm
            if not (lo[Position.FWD] <= nf <= hi[Position.FWD]):
                continue
            if len(por_pos[Position.DEF]) < nd or len(por_pos[Position.MID]) < nm \
               or len(por_pos[Position.FWD]) < nf or not por_pos[Position.GKP]:
                continue
            xi = (por_pos[Position.GKP][:1] + por_pos[Position.DEF][:nd]
                  + por_pos[Position.MID][:nm] + por_pos[Position.FWD][:nf])
            v = sum(c[key] for c in xi)
            if mejor is None or v > mejor[0]:
                mejor = (v, xi)
    return mejor[1] if mejor else []


def _prepara(results: pd.DataFrame) -> pd.DataFrame:
    """Colapsa dobles jornadas y normaliza columnas."""
    if results.empty or "position" not in results.columns:
        return pd.DataFrame()
    df = (results.groupby("element")
          .agg(points=("total_points", "sum"), minutes=("minutes", "sum"),
               selected=("selected", "max"), value=("value", "max"),
               position=("position", "first"), team=("team", "first"))
          .reset_index())
    df = df.dropna(subset=["position", "team"])
    if df.empty:
        return df
    # 2024/25 contiene activos del chip Assistant Manager (posicion ``AM``).
    # No forman parte de una plantilla normal de 15 y por tanto tampoco deben
    # contaminar los baselines de jugadores.
    def playable_position(raw):
        try:
            return Position.parse(raw)
        except ValueError:
            return None

    df["position"] = df["position"].map(playable_position)
    df = df.dropna(subset=["position"])
    df["price"] = df["value"] / 10.0
    return df


def template(results: pd.DataFrame, rules: dict) -> int:
    """Lo que hace la multitud: los mas seleccionados, capitan el mas popular."""
    df = _prepara(results)
    if df.empty:
        return 0
    squad = _armar(df, rules, "selected", rules["budget"])
    if not squad:
        return 0
    xi = _mejor_xi(squad, rules, "selected")
    cap = max(xi, key=lambda c: c["selected"]) if xi else None
    return int(sum(c["points"] for c in xi) + (cap["points"] if cap else 0))


def ceiling(results: pd.DataFrame, rules: dict) -> int:
    """Techo con informacion perfecta: el mejor equipo posible en retrospectiva.

    No es alcanzable. Sirve para saber que fraccion de lo posible se capturo,
    que es mas informativo que compararse con una media.
    """
    df = _prepara(results)
    if df.empty:
        return 0
    squad = _armar(df, rules, "points", rules["budget"])
    if not squad:
        return 0
    xi = _mejor_xi(squad, rules, "points")
    cap = max(xi, key=lambda c: c["points"]) if xi else None
    return int(sum(c["points"] for c in xi) + (cap["points"] if cap else 0))


def random_valid(results: pd.DataFrame, rules: dict, seed: int) -> int:
    """Plantilla valida al azar. El piso de verdad."""
    df = _prepara(results)
    if df.empty:
        return 0
    rng = random.Random(seed)
    df = df.copy()
    df["_r"] = [rng.random() for _ in range(len(df))]
    squad = _armar(df, rules, "_r", rules["budget"])
    if not squad:
        return 0
    xi = _mejor_xi(squad, rules, "_r")
    cap = max(xi, key=lambda c: c["_r"]) if xi else None
    return int(sum(c["points"] for c in xi) + (cap["points"] if cap else 0))


def all_baselines(results: pd.DataFrame, rules: dict, seed: int) -> dict:
    return {
        "template": template(results, rules),
        "random": random_valid(results, rules, seed),
        "ceiling": ceiling(results, rules),
    }
