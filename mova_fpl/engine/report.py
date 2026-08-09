"""Acta de decision. El entregable que Julian introduce a mano en FPL.

No hay escritura automatica contra la API (ADR-006, REQ-S-002): el motor propone
y una persona ejecuta. Por eso el acta tiene que bastarse sola — quince nombres,
precios, el once, el capitan, y el porque de cada uno en numeros.

Todo lo que aparece aqui es trazable: version de modelo, git sha, momento de
emision y de donde salio cada dato. Un acta sin procedencia no es evidencia.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from mova_fpl.rules.base import Position
from mova_fpl.rules.squad import validate_squad

ORDEN = {Position.GKP: 0, Position.DEF: 1, Position.MID: 2, Position.FWD: 3}


@dataclass(frozen=True, slots=True)
class Acta:
    texto: str
    violaciones: tuple
    total: float
    banco: float

    @property
    def valida(self) -> bool:
        return not self.violaciones


def _fila(r, desglose: dict, capitan: int, vice: int) -> str:
    marca = " **(C)**" if r["element"] == capitan else (" *(V)*" if r["element"] == vice else "")
    d = desglose.get(r["element"], {})
    partes = []
    for etiqueta, clave in (("gol", "pts_goles"), ("asi", "pts_asistencias"),
                            ("cs", "pts_cs"), ("def", "pts_defcon"), ("bon", "pts_bonus")):
        v = d.get(clave, 0.0)
        if abs(v) >= 0.15:
            partes.append(f"{etiqueta} {v:+.1f}")
    aviso = ""
    if r.get("estado", "a") != "a":
        aviso = f" ⚠️ {r.get('estado')}" + (f" — {r['parte'][:60]}" if r.get("parte") else "")
    return (f"| {r['position']} | {r['name']}{marca} | {r['team']} | £{r['value']/10:.1f} | "
            f"{d.get('xp', 0.0):.2f} | ±{d.get('xp_sd', 0.0):.1f} | "
            f"{int(round(100 * d.get('p_60', 0.0)))}% | {' · '.join(partes) or '—'}{aviso} |")


def _vigencia(meta: dict) -> list:
    """Avisa si el acta se emitio con demasiada antelacion.

    Un acta a doce dias del cierre es un borrador: los precios se mueven, el parte
    medico cambia y las alineaciones probables todavia no existen. Vale para
    planear, no para introducir. La unica que cuenta es la ultima.
    """
    dias = meta.get("dias_al_deadline")
    if dias is None or dias <= 2:
        return []
    return ["", f"> ⚠️ **Emitida {dias:.1f} días antes del cierre: esto es un borrador.** "
                "Los precios se mueven a diario, el parte médico cambia y las alineaciones "
                "probables aún no existen. Volver a correr dentro de las 24 horas previas "
                "al deadline y usar esa acta, no esta.", ""]


def render(decision, roster: pd.DataFrame, desglose: pd.DataFrame, meta: dict) -> Acta:
    """Compone el acta y valida la plantilla contra las reglas de la temporada."""
    por_id = {int(r["element"]): r for _, r in roster.iterrows()}
    det = {int(r["element"]): r.to_dict() for _, r in desglose.iterrows()}
    rules = meta["rules"]

    from mova_fpl.rules.base import Squad, SquadPlayer
    jugadores = tuple(
        SquadPlayer(element=e, position=Position.parse(por_id[e]["position"]),
                    team=str(por_id[e]["team"]), price=float(por_id[e]["value"]) / 10.0)
        for e in decision.squad_15)
    squad = Squad(players=jugadores, starters=decision.starters, captain=decision.captain,
                  vice_captain=decision.vice_captain, bench_order=decision.bench_order,
                  bank=decision.bank_after)
    violaciones = tuple(validate_squad(squad, rules))

    coste = sum(float(por_id[e]["value"]) / 10.0 for e in decision.squad_15)
    en_xi = list(decision.starters)
    banca = list(decision.bench_order)
    clave = lambda e: (ORDEN[Position.parse(por_id[e]["position"])],      # noqa: E731
                       -det.get(e, {}).get("xp", 0.0))

    cab = ["| Pos | Jugador | Club | Precio | xP | ± | P(60') | Desglose |",
           "|---|---|---|---:|---:|---:|---:|---|"]
    lineas = [
        f"# Acta de decisión · FPL {meta['season']} · Gameweek {decision.gw}", "",
        f"**Emitida:** {meta['emitida']}  ",
        f"**Deadline:** {meta['deadline']}  ",
        f"**Política:** `{meta['policy']}` · horizonte {meta['horizon']}  ",
        f"**Modelos:** minutos `{meta['v_minutes']}` · puntos `{meta['v_points']}`  ",
        f"**git sha:** `{meta['git_sha']}`  ",
        f"**Fuente:** {meta['fuente']}", "",
        *_vigencia(meta), "---", "", "## Once inicial", "", *cab,
        *[_fila(por_id[e], det, decision.captain, decision.vice_captain)
          for e in sorted(en_xi, key=clave)], "",
        "## Banquillo", "",
        "El orden importa: es la prioridad de las sustituciones automáticas.", "", *cab,
        *[_fila(por_id[e], det, decision.captain, decision.vice_captain) for e in banca], "",
        "## Resumen", "",
        "| | |", "|---|---:|",
        f"| Coste de la plantilla | £{coste:.1f}M |",
        f"| Banco | £{decision.bank_after:.1f}M |",
        f"| xP del once (con capitán) | {decision.expected_points:.1f} |",
        f"| Transferencias | {len(decision.transfers_in)} |",
        f"| Hits | −{decision.hits} |",
        f"| Capitán | {por_id[decision.captain]['name']} |",
        f"| Vicecapitán | {por_id[decision.vice_captain]['name']} |", "",
        "## Validación de reglas", "",
    ]
    if violaciones:
        lineas += ["**LA PLANTILLA NO ES VÁLIDA. No introducir.**", ""]
        lineas += [f"- `{v.code}` — {v.detail}" for v in violaciones]
    else:
        lineas.append(f"`validate_squad` con las reglas {meta['season']} devuelve **[]** — "
                      "sin violaciones.")

    avisos = [r for r in (por_id[e] for e in decision.squad_15) if r.get("estado", "a") != "a"]
    if avisos:
        lineas += ["", "## Avisos del parte médico", "",
                   "Estos jugadores entraron con la probabilidad de jugar ya descontada; "
                   "aun así conviene revisarlos antes del deadline.", "",
                   "| Jugador | Estado | Parte |", "|---|---|---|"]
        lineas += [f"| {r['name']} | `{r['estado']}` | {r.get('parte') or '—'} |" for r in avisos]

    if decision.notes:
        lineas += ["", "## Notas del motor", ""] + [f"- {n}" for n in decision.notes]

    lineas += ["", "---", "",
               f"Huella de la decisión: `{decision.fingerprint()}`  ",
               "Este documento se introduce **a mano** en la web de FPL. El motor no "
               "escribe contra la API (ADR-006)."]

    return Acta(texto="\n".join(lineas) + "\n", violaciones=violaciones,
                total=round(coste, 1), banco=decision.bank_after)
