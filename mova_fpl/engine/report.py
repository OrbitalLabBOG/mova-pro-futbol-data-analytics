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
    avisos = []
    contexto = meta.get("event_context") or {}
    if contexto.get("preliminary"):
        prior = contexto.get("prior_gw") or "anterior"
        faltan = int(contexto.get("prior_unstarted_fixtures") or 0)
        detalle = (f" y todavía faltan {faltan} partido(s) por comenzar" if faltan else "")
        avisos += [
            "",
            f"> ⚠️ **Preliminar: la GW{prior} no está asentada{detalle}.** "
            "No promover chips ni transferencias a decisión final hasta que FPL marque "
            "la jornada como terminada y data_checked.",
            "",
        ]
    dias = meta.get("dias_al_deadline")
    if dias is not None and dias > 2:
        avisos += ["", f"> ⚠️ **Emitida {dias:.1f} días antes del cierre: esto es un borrador.** "
                    "Los precios se mueven a diario, el parte médico cambia y las alineaciones "
                    "probables aún no existen. Volver a correr dentro de las 24 horas previas "
                    "al deadline y usar esa acta, no esta.", ""]
    return avisos


def _transferencias(decision, por_id: dict, rules: dict) -> list:
    """Lista las operaciones propuestas sin inventar emparejamientos uno-a-uno."""
    entradas = [por_id[e]["name"] for e in decision.transfers_in]
    salidas = [por_id[e]["name"] for e in decision.transfers_out]
    if not entradas and not salidas:
        return ["", "## Transferencias propuestas", "", "**Ninguna.**"]
    coste = int(decision.hits) * int(rules.get("hit_cost", 4))
    return [
        "", "## Transferencias propuestas", "",
        f"**Salen ({len(salidas)}):** {', '.join(salidas) or '—'}.",
        f"**Entran ({len(entradas)}):** {', '.join(entradas) or '—'}.",
        "",
        f"Impacto: {decision.hits} hit(s), **−{coste} puntos**. "
        "Las listas no representan emparejamientos uno-a-uno.",
    ]


def _chips(decision, meta: dict) -> list:
    """Que se hizo con los chips y por que. En prosa, no en jerga.

    Un acta que dice "chip: None" no informa: no distingue entre "no habia
    ninguno" y "habia cuatro y ninguno valia la pena". La diferencia es
    justamente la decision.
    """
    catalogo = meta.get("catalogo_chips")
    if catalogo is None:
        return []

    usados = meta.get("chips_used") or ()
    veredicto = meta.get("chip_verdict")
    gw = decision.gw
    ventana = catalogo.window_for(gw)

    out = ["", "## Chips", ""]
    if decision.chip:
        out.append(f"**Se juega el {decision.chip.replace('_', ' ').upper()} en esta jornada.**")
        if veredicto:
            out.append("")
            out.append(f"Vale **+{veredicto.value:.1f} puntos esperados** frente a no jugarlo, "
                       f"contra un umbral de {veredicto.threshold:.1f}. {veredicto.reason.capitalize()}.")
    elif veredicto and veredicto.candidates:
        detalle = " · ".join(f"`{c}` {v:+.1f}" for c, v in sorted(veredicto.candidates.items(),
                                                                  key=lambda kv: -kv[1]))
        out.append(f"**No se juega ninguno.** {veredicto.reason.capitalize()}.")
        out += ["", f"Valorados esta jornada: {detalle}. "
                    f"Ninguno supera su umbral ({veredicto.threshold:.1f})."]
    elif veredicto:
        out.append(f"**No hay chips disponibles.** {veredicto.reason.capitalize()}.")
    else:
        out.append("**Ninguno.** El planificador no corrio en esta jornada.")

    if ventana is not None:
        from mova_fpl.rules.chips import ChipUse, available
        # el chip que se juega HOY ya no esta disponible: contarlo entre los que
        # quedan haria que el acta se contradijera consigo misma.
        tras_hoy = tuple(usados) + ((ChipUse(gw=gw, chip=decision.chip),) if decision.chip else ())
        quedan = sorted(available(gw + 1, tras_hoy, catalogo)) if gw < ventana.last_gw else []
        restantes = ventana.remaining(gw) - (1 if decision.chip else 0)
        out += ["", f"Ventana **{ventana.name}** (GW{ventana.first_gw}–{ventana.last_gw}): "
                    f"quedan **{max(0, restantes)} jornadas** para usarla."]
        if quedan:
            out.append(f"Sin gastar tras esta jornada: {', '.join(f'`{c}`' for c in quedan)}.")
            if 0 < restantes <= 3:
                out.append(f"\n> ⚠️ **Quedan {restantes} jornadas y {len(quedan)} chips sin usar.** "
                           "Lo que no se juegue antes del cierre de la ventana se pierde: "
                           "no se arrastra a la segunda vuelta.")
        else:
            out.append("Todos los de esta ventana ya se gastaron.")
    if usados:
        gastados = ", ".join(f"`{u.chip}` en la GW{u.gw}" for u in usados)
        out += ["", f"Historial de la temporada: {gastados}."]
    return out


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
    violaciones = list(validate_squad(squad, rules))
    catalogo = meta.get("catalogo_chips")
    if catalogo is not None and decision.chip:
        from mova_fpl.rules.chips import validate_chip
        violaciones += validate_chip(decision.chip, decision.gw,
                                     meta.get("chips_used") or (), catalogo)
    violaciones = tuple(violaciones)

    coste = sum(float(por_id[e]["value"]) / 10.0 for e in decision.squad_15)
    en_xi = list(decision.starters)
    banca = list(decision.bench_order)
    clave = lambda e: (ORDEN[Position.parse(por_id[e]["position"])],      # noqa: E731
                       -det.get(e, {}).get("xp", 0.0))

    cab = ["| Pos | Jugador | Club | Precio | xP | ± | P(60') | Desglose |",
           "|---|---|---|---:|---:|---:|---:|---|"]
    lineas = [
        f"# Acta de decisión · FPL {meta['season']} · Gameweek {decision.gw}", "",
        f"**Emitida:** {meta['emitida']}",
        f"**Deadline:** {meta['deadline']}",
        f"**Política:** `{meta['policy']}` · horizonte {meta['horizon']}",
        f"**Modelos:** minutos `{meta['v_minutes']}` · puntos `{meta['v_points']}`",
        f"**git sha:** `{meta['git_sha']}`",
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
        f"| Hits | {decision.hits} (−{int(decision.hits) * int(rules.get('hit_cost', 4))} pts) |",
        *([f"| Chip | **{decision.chip}** |"] if decision.chip else []),
        f"| Capitán | {por_id[decision.captain]['name']} |",
        f"| Vicecapitán | {por_id[decision.vice_captain]['name']} |",
        *_transferencias(decision, por_id, rules),
        *_chips(decision, meta), "",
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
               f"Huella de la decisión: `{decision.fingerprint()}`",
               "Este documento se introduce **a mano** en la web de FPL. El motor no "
               "escribe contra la API (ADR-006)."]

    return Acta(texto="\n".join(lineas) + "\n", violaciones=violaciones,
                total=round(coste, 1), banco=decision.bank_after)
