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
    out["chips"] += _diff_chips(ra.CHIPS, rb.CHIPS)
    return out


def _diff_chips(ca, cb) -> list[str]:
    """Catalogo de chips: nombres, ventanas y ejemplares por ventana.

    Las ventanas importan tanto como los nombres: la reforma de 2025/26 no anadio
    chips nuevos, duplico los que ya habia partiendo la temporada en dos.
    """
    fuera: list[str] = []
    if set(ca.chips) != set(cb.chips):
        fuera.append(f"tipos: {sorted(ca.chips)} -> {sorted(cb.chips)}")
    va = [(w.name, w.first_gw, w.last_gw) for w in ca.windows]
    vb = [(w.name, w.first_gw, w.last_gw) for w in cb.windows]
    if va != vb:
        fuera.append(f"ventanas: {va} -> {vb}")
    if ca.per_window != cb.per_window:
        fuera.append(f"ejemplares por ventana: {ca.per_window} -> {cb.per_window}")
    if ca.total() != cb.total():
        fuera.append(f"total de chips por temporada: {ca.total()} -> {cb.total()}")
    return fuera


def render(a: str, b: str) -> str:
    d = compute(a, b)
    lines = [f"# Diff de reglas: {a} -> {b}", ""]
    for seccion, titulo in (("scoring", "Puntuacion"), ("bps", "Bonus Points System"),
                            ("squad", "Plantilla"), ("chips", "Chips")):
        lines.append(f"## {titulo}")
        lines += [f"- {c}" for c in d[seccion]] or ["- sin cambios"]
        lines.append("")
    return "\n".join(lines)
