"""Politicas de decision. La del walking skeleton es voraz y deliberadamente simple."""
from __future__ import annotations

from collections import Counter

from mova_fpl.engine.greedy import as_items, build_squad
from mova_fpl.engine.state import Candidate, Decision, State
from mova_fpl.rules.base import Position
from mova_fpl.rules.market import transfer_cost
from mova_fpl.rules.money import to_millions, to_tenths

ORDEN_BANCA = (Position.DEF, Position.MID, Position.FWD)


def select_squad_greedy(candidates, rules: dict, budget: float) -> list[Candidate]:
    """15 jugadores por xp descendente. Delega en el constructor compartido, que
    respeta cuotas de club en el lookahead de coste."""
    por_id = {c.element: c for c in candidates}
    ids = build_squad(as_items(candidates, "element", "position", "team", "price", "xp"),
                      rules, budget)
    return [por_id[i] for i in ids]


def pick_lineup(squad: list[Candidate], rules: dict):
    """XI que maximiza xp entre las formaciones validas. Devuelve (XI, banca, C, VC)."""
    por_pos = {p: sorted([c for c in squad if c.position is p], key=lambda c: -c.xp)
               for p in Position}
    mejor = None
    lo, hi = rules["formation_min"], rules["formation_max"]
    for ndef in range(lo[Position.DEF], hi[Position.DEF] + 1):
        for nmid in range(lo[Position.MID], hi[Position.MID] + 1):
            nfwd = rules["starters"] - 1 - ndef - nmid
            if not (lo[Position.FWD] <= nfwd <= hi[Position.FWD]):
                continue
            if len(por_pos[Position.DEF]) < ndef or len(por_pos[Position.MID]) < nmid \
               or len(por_pos[Position.FWD]) < nfwd or not por_pos[Position.GKP]:
                continue
            xi = (por_pos[Position.GKP][:1] + por_pos[Position.DEF][:ndef]
                  + por_pos[Position.MID][:nmid] + por_pos[Position.FWD][:nfwd])
            total = sum(c.xp for c in xi)
            if mejor is None or total > mejor[0]:
                mejor = (total, xi)

    if mejor is None:
        raise ValueError("ninguna formacion valida con esta plantilla")

    xi = sorted(mejor[1], key=lambda c: -c.xp)
    en_xi = {c.element for c in xi}
    gk_banca = [c for c in squad if c.position is Position.GKP and c.element not in en_xi]
    campo_banca = sorted([c for c in squad if c.position is not Position.GKP and c.element not in en_xi],
                         key=lambda c: -c.xp)
    banca = gk_banca + campo_banca            # el GKP suplente va primero, como en FPL
    return xi, banca, xi[0], xi[1]


def greedy_policy(state: State, config) -> Decision:
    """Politica del walking skeleton: arma de cero en GW1, luego 0 o 1 transferencia."""
    rules = state.rules
    notas: list[str] = []

    if state.is_cold_start:
        squad = select_squad_greedy(state.candidates, rules, rules["budget"])
        entra, sale, hits = (), (), 0
        notas.append("cold start: plantilla construida desde cero")
    else:
        actuales, en_blanco = _plantilla_actual(state)
        if en_blanco:
            notas.append(f"{en_blanco} jugadores en jornada en blanco (xp=0, siguen en plantilla)")
        squad, entra, sale = _mejor_transferencia(actuales, state, rules)
        hits = transfer_cost(len(entra), state.free_transfers, rules["hit_cost"])

    xi, banca, cap, vice = pick_lineup(squad, rules)
    coste = round(sum(c.price for c in squad), 1)
    esperado = sum(c.xp for c in xi) + cap.xp - hits

    return Decision(
        season=state.season, gw=state.gw,
        squad_15=tuple(c.element for c in squad),
        starters=tuple(c.element for c in xi),
        captain=cap.element, vice_captain=vice.element,
        bench_order=tuple(c.element for c in banca),
        transfers_in=tuple(entra), transfers_out=tuple(sale), hits=hits,
        expected_points=round(esperado, 2), total_cost=coste,
        bank_after=round(rules["budget"] - coste, 1),
        policy="greedy-stub", notes=tuple(notas),
    )


def _plantilla_actual(state: State) -> tuple[list[Candidate], int]:
    """Convierte la plantilla vigente en candidatos, sin perder a nadie.

    Un jugador cuyo equipo no disputa esta jornada (JORNADA EN BLANCO) no tiene
    fila en el catalogo, pero sigue en la plantilla: puntua 0, no desaparece.
    Borrarlo dejaba plantillas de menos de 15 sin formacion valida.
    """
    by_id = state.by_id()
    fuera = 0
    out: list[Candidate] = []
    for p in state.squad.players:
        c = by_id.get(p.element)
        if c is not None:
            out.append(c)
        else:
            fuera += 1
            out.append(Candidate(element=p.element, position=p.position, team=p.team,
                                 price=p.price, xp=0.0, name=f"blank_{p.element}"))
    return out, fuera


def _mejor_transferencia(actuales, state: State, rules: dict):
    """Una transferencia si mejora el xp del XI mas alla del coste del hit."""
    base_xi, _, base_cap, _ = pick_lineup(actuales, rules)
    base = sum(c.xp for c in base_xi) + base_cap.xp
    en_plantilla = {c.element for c in actuales}
    clubes = Counter(c.team for c in actuales)
    presupuesto = sum(to_tenths(c.price) for c in actuales) + to_tenths(state.bank)

    peores = sorted(actuales, key=lambda c: c.xp)[:5]
    mejores = sorted((c for c in state.candidates if c.element not in en_plantilla),
                     key=lambda c: -c.xp)[:25]

    mejor = (base, actuales, (), ())
    coste_hit = transfer_cost(1, state.free_transfers, rules["hit_cost"])
    for fuera in peores:
        for dentro in mejores:
            if dentro.position is not fuera.position:
                continue
            if dentro.team != fuera.team and clubes[dentro.team] >= rules["max_per_club"]:
                continue
            nueva = [c for c in actuales if c.element != fuera.element] + [dentro]
            if sum(to_tenths(c.price) for c in nueva) > presupuesto:
                continue
            try:
                xi, _, cap, _ = pick_lineup(nueva, rules)
            except ValueError:
                continue
            valor = sum(c.xp for c in xi) + cap.xp - coste_hit
            if valor > mejor[0] + 1e-9:
                mejor = (valor, nueva, (dentro.element,), (fuera.element,))
    return mejor[1], mejor[2], mejor[3]


POLICIES = {"greedy-stub": greedy_policy}


# --------------------------------------------------------------- WP-006: MILP

def optimizer_config(config, n_gws: int):
    """Traduce la config del motor a la del optimizador.

    Vive aqui, y no dentro de `milp_policy`, porque el planificador de chips
    necesita EXACTAMENTE la misma configuracion para que sus solves hipoteticos
    sean comparables con el solve real. Dos construcciones separadas se
    desincronizan y el valor estimado de un chip deja de significar nada.
    """
    from mova_fpl.optimizer import OptimizerConfig
    return OptimizerConfig(
        horizon=n_gws, decay=getattr(config, "decay", 0.84),
        bench_weight=getattr(config, "bench_weight", 0.12),
        top_k=getattr(config, "top_k", 30),
        max_hits_per_gw=getattr(config, "max_hits", 2),
        time_limit=getattr(config, "time_limit", 30),
    )


def milp_policy(state: State, config) -> Decision:
    """Optimizador exacto sobre un horizonte de N jornadas.

    A diferencia de la voraz, no decide "la mejor transferencia de esta semana":
    decide la mejor SECUENCIA de plantillas para el horizonte y ejecuta solo el
    primer paso. Eso es lo que permite ahorrar transferencias para una doble
    jornada o vender antes de una en blanco.
    """
    from mova_fpl.optimizer import OptimizerConfig, solve
    from mova_fpl.optimizer.horizon import summarize

    gw = state.gw
    xp = state.horizon_xp or {gw: {c.element: c.xp for c in state.candidates}}
    ocfg = optimizer_config(config, len(xp))

    # El free hit no pasa por el MILP: su plantilla revierte y se resuelve aparte.
    if "free_hit" in (state.chips_allowed.get(gw) or ()):
        return _decision_free_hit(state, xp, ocfg)

    sol = solve(state, xp, ocfg)

    fila = xp[gw]
    atributos = {c.element: c for c in state.candidates}
    for p in (state.squad.players if state.squad else ()):
        atributos.setdefault(p.element, Candidate(element=p.element, position=p.position,
                                                  team=p.team, price=p.price, xp=0.0))

    squad = [atributos[i] for i in sol.squad[gw]]
    xi = sorted(sol.starters[gw], key=lambda i: -fila.get(i, 0.0))
    cap = sol.captain[gw]
    vice = next((i for i in xi if i != cap), None)

    en_xi = set(xi)
    banca_gk = [i for i in sol.squad[gw] if i not in en_xi
                and atributos[i].position is Position.GKP]
    banca_campo = sorted((i for i in sol.squad[gw] if i not in en_xi
                          and atributos[i].position is not Position.GKP),
                         key=lambda i: -fila.get(i, 0.0))

    coste = to_millions(sum(to_tenths(atributos[i].price) for i in sol.squad[gw]))
    esperado = sum(fila.get(i, 0.0) for i in xi) + fila.get(cap, 0.0) - sol.hits[gw]

    chip = sol.chips.get(gw)
    notas = [str(sol.shortlist), f"horizonte {sorted(xp)} xp_total={summarize(xp)}"]
    if chip:
        notas.append(f"chip jugado: {chip}")
    futuras = {g: len(sol.buys[g]) for g in sorted(xp)[1:] if sol.buys[g]}
    if futuras:
        notas.append(f"plan de transferencias futuras (no ejecutado): {futuras}")
    if state.squad is None:
        notas.append("cold start: plantilla construida desde cero")

    return Decision(
        season=state.season, gw=gw,
        squad_15=tuple(c.element for c in squad),
        starters=tuple(xi), captain=cap, vice_captain=vice,
        bench_order=tuple(banca_gk + banca_campo),
        transfers_in=() if state.squad is None else tuple(sorted(sol.buys[gw])),
        transfers_out=() if state.squad is None else tuple(sorted(sol.sells[gw])),
        hits=sol.hits[gw], chip=chip,
        expected_points=round(esperado, 2), total_cost=coste,
        bank_after=to_millions(sol.bank[gw]),
        policy="milp", notes=tuple(notas),
    )


def _decision_free_hit(state: State, xp: dict, ocfg) -> Decision:
    """Plantilla de una sola jornada. El simulador la revierte al cierre siguiente.

    `transfers_in/out` quedan VACIOS a proposito: un free hit no mueve la plantilla
    real, y contarlos como transferencias corromperia el arrastre de libres.
    """
    from mova_fpl.optimizer.freehit import evaluate as evaluate_free_hit

    gw = state.gw
    plan = evaluate_free_hit(state, xp[gw], ocfg)
    fila = xp[gw]
    atributos = {c.element: c for c in state.candidates}
    for p in (state.squad.players if state.squad else ()):
        atributos.setdefault(p.element, Candidate(element=p.element, position=p.position,
                                                  team=p.team, price=p.price, xp=0.0))

    xi = sorted(plan.starters, key=lambda i: -fila.get(i, 0.0))
    cap = plan.captain
    vice = next((i for i in xi if i != cap), None)
    en_xi = set(xi)
    banca_gk = [i for i in plan.squad if i not in en_xi
                and atributos[i].position is Position.GKP]
    banca_campo = sorted((i for i in plan.squad if i not in en_xi
                          and atributos[i].position is not Position.GKP),
                         key=lambda i: -fila.get(i, 0.0))
    coste = to_millions(sum(to_tenths(atributos[i].price) for i in plan.squad))
    esperado = sum(fila.get(i, 0.0) for i in xi) + fila.get(cap, 0.0)

    return Decision(
        season=state.season, gw=gw,
        squad_15=tuple(plan.squad), starters=tuple(xi), captain=cap, vice_captain=vice,
        bench_order=tuple(banca_gk + banca_campo),
        transfers_in=(), transfers_out=(), hits=0, chip="free_hit",
        expected_points=round(esperado, 2), total_cost=coste,
        bank_after=round(plan.budget - coste, 1),
        policy="milp",
        notes=(f"free hit: plantilla de una jornada con {plan.budget:.1f}M "
               f"(+{plan.value:.1f} xp sobre no jugarlo); revierte al cierre siguiente",),
    )


POLICIES["milp"] = milp_policy
