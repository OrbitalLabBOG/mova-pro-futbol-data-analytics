"""Diff entre versiones de reglas. Puro: calcula y renderiza, no escribe.

El CLI que persiste el resultado vive en mova_fpl/cli/rules_diff.py, porque
escribir ficheros es I/O y rules/ no hace I/O.
"""
from __future__ import annotations

from mova_fpl.rules import get


def compute(a: str, b: str) -> dict:
    ra, rb = get(a), get(b)
    out = {"scoring": [], "bps": ra.BPS.diff(rb.BPS), "squad": [], "chips": []}

    for campo in ("goal_points", "clean_sheet_points", "defcon_thresholds"):
        va, vb = getattr(ra.SCORING, campo), getattr(rb.SCORING, campo)
        if va != vb:
            out["scoring"].append(f"{campo}: {va} -> {vb}")
    for campo in ("assist_points", "appearance_short", "appearance_long", "minutes_for_long",
                  "saves_per_point", "penalty_save_points", "penalty_miss_points",
                  "yellow_card_points", "red_card_points", "own_goal_points", "defcon_points"):
        va, vb = getattr(ra.SCORING, campo), getattr(rb.SCORING, campo)
        if va != vb:
            out["scoring"].append(f"{campo}: {va} -> {vb}")

    for k in sorted(set(ra.SQUAD) | set(rb.SQUAD)):
        if ra.SQUAD.get(k) != rb.SQUAD.get(k):
            out["squad"].append(f"{k}: {ra.SQUAD.get(k)} -> {rb.SQUAD.get(k)}")
    if set(ra.CHIPS) != set(rb.CHIPS):
        out["chips"].append(f"{ra.CHIPS} -> {rb.CHIPS}")
    return out


def render(a: str, b: str) -> str:
    d = compute(a, b)
    lines = [f"# Diff de reglas: {a} -> {b}", ""]
    for seccion, titulo in (("scoring", "Puntuacion"), ("bps", "Bonus Points System"),
                            ("squad", "Plantilla"), ("chips", "Chips")):
        lines.append(f"## {titulo}")
        lines += [f"- {c}" for c in d[seccion]] or ["- sin cambios"]
        lines.append("")
    return "\n".join(lines)
