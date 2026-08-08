"""Programa entero mixto para plantilla, XI y capitan sobre un horizonte rodante.

Funcion objetivo (Q-02)
-----------------------
v1 maximiza PUNTOS ESPERADOS, sin termino de riesgo. Es el objetivo correcto para
rank global: en una poblacion de millones, la media es el objetivo y la varianza
no se premia. Para una mini-liga pequena el objetivo cambia — hay que separarse
del rival, no del promedio — pero ese cambio es UN TERMINO MAS en la misma
funcion, no otra formulacion. Por eso `OptimizerConfig.risk_lambda` existe y vale
cero: cuando se decida jugar mini-liga, se activa sin reescribir el modelo.
Ver ADR-007.

Que se modela y que no
----------------------
SI: composicion 2/5/5/3, presupuesto real (banco + precio de venta, no 100M fijos),
maximo tres por club, formaciones validas, capitan, transferencias con acumulacion
de libres y coste de hits, dobles jornadas y jornadas en blanco.

NO: chips (heuristica aparte, Q-04), precio futuro de los jugadores, vicecapitan
(solo importa si el capitan no juega; se asigna despues por xp), y sustituciones
automaticas (el banquillo entra al objetivo con un peso, no como decision).

Si el problema es infactible falla ruidosamente con el diagnostico. Nunca relaja
una restriccion en silencio.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import pulp

from mova_fpl.optimizer.heuristics import DEFAULT_CHEAPEST, DEFAULT_TOP_K, shortlist
from mova_fpl.optimizer.horizon import DEFAULT_DECAY
from mova_fpl.rules.base import Position
from mova_fpl.rules.market import selling_price
from mova_fpl.rules.money import to_millions, to_tenths

#: transferencias libres nominales en el arranque en frio: la plantilla es gratis
COLD_START_FT = 15


class Infeasible(RuntimeError):
    """No existe solucion valida. Trae la lista de restricciones que lo impiden."""

    def __init__(self, motivos: list[str]):
        self.motivos = motivos
        super().__init__("problema infactible:\n  - " + "\n  - ".join(motivos))


@dataclass(frozen=True, slots=True)
class OptimizerConfig:
    horizon: int = 1
    decay: float = DEFAULT_DECAY
    #: peso del banquillo en el objetivo. Aproxima el valor de las sustituciones
    #: automaticas sin modelarlas: un suplente vale algo, pero mucho menos que un titular.
    bench_weight: float = 0.12
    top_k: int = DEFAULT_TOP_K
    cheapest: int = DEFAULT_CHEAPEST
    max_hits_per_gw: int = 2
    time_limit: int = 30
    risk_lambda: float = 0.0          # Q-02: 0 = rank global, neutral al riesgo
    tie_break: float = 1e-6           # a igual xp, prefiere plantilla mas barata
    solver_msg: bool = False


@dataclass(frozen=True, slots=True)
class Solution:
    """Resultado crudo del solver, antes de volverse `Decision`."""
    squad: dict            # gw -> tuple[element]
    starters: dict         # gw -> tuple[element]
    captain: dict          # gw -> element
    buys: dict             # gw -> tuple[element]
    sells: dict            # gw -> tuple[element]
    hits: dict             # gw -> int
    bank: dict             # gw -> decimas enteras
    objective: float
    status: str
    shortlist: object


# --------------------------------------------------------------------- modelo

def solve(state, xp_matrix: dict, config: OptimizerConfig | None = None) -> Solution:
    """Resuelve el horizonte y devuelve la solucion completa.

    `state` aporta plantilla vigente, banco, transferencias libres y reglas.
    `xp_matrix` es {gw: {element: xp}} y define implicitamente el horizonte.
    """
    config = config or OptimizerConfig()
    rules = state.rules
    gws = sorted(xp_matrix)
    if not gws:
        raise ValueError("xp_matrix vacia: no hay jornadas que optimizar")
    if gws[0] != state.gw:
        raise ValueError(f"la matriz empieza en gw={gws[0]} y el estado esta en gw={state.gw}")

    pool = _pool(state)
    en_plantilla = {p.element for p in state.squad.players} if state.squad else set()
    pool, informe = shortlist(pool, xp_matrix, keep_ids=en_plantilla,
                              top_k=config.top_k, cheapest=config.cheapest)

    precio = {c.element: to_tenths(c.price) for c in pool}
    venta = _sale_values(state, pool, precio)
    banco0 = to_tenths(state.bank) if state.squad else 0
    if state.squad is None:
        banco0 = to_tenths(rules["budget"])

    _precheck(pool, rules, banco0 + sum(venta.get(e, 0) for e in en_plantilla), en_plantilla)

    prob = pulp.LpProblem("fpl_horizonte", pulp.LpMaximize)
    ids = [c.element for c in pool]
    pos = {c.element: c.position for c in pool}
    club = {c.element: c.team for c in pool}
    frio = state.squad is None

    s, e, cap, buy, sell = {}, {}, {}, {}, {}
    hits, ft, bank = {}, {}, {}
    for g in gws:
        for i in ids:
            s[i, g] = pulp.LpVariable(f"s_{i}_{g}", cat="Binary")
            e[i, g] = pulp.LpVariable(f"e_{i}_{g}", cat="Binary")
            cap[i, g] = pulp.LpVariable(f"c_{i}_{g}", cat="Binary")
            buy[i, g] = pulp.LpVariable(f"b_{i}_{g}", cat="Binary")
            sell[i, g] = pulp.LpVariable(f"d_{i}_{g}", cat="Binary")
        hits[g] = pulp.LpVariable(f"h_{g}", lowBound=0, upBound=config.max_hits_per_gw, cat="Integer")
        bank[g] = pulp.LpVariable(f"bank_{g}", lowBound=0, cat="Continuous")

    # Las transferencias libres de la jornada que se decide son un DATO. Solo las
    # de las jornadas futuras son variables, porque dependen de lo que se decida hoy.
    for g in gws[1:]:
        ft[g] = pulp.LpVariable(f"ft_{g}", lowBound=1, upBound=rules["max_free_transfers"],
                                cat="Integer")
    libres_hoy = COLD_START_FT if frio else min(int(state.free_transfers),
                                                rules["max_free_transfers"])

    for idx, g in enumerate(gws):
        _restricciones_plantilla(prob, ids, pos, club, s, e, cap, rules, g)

        previo = ((lambda i: (1 if i in en_plantilla else 0)) if idx == 0
                  else (lambda i: s[i, gws[idx - 1]]))
        for i in ids:
            prob += s[i, g] == previo(i) + buy[i, g] - sell[i, g], f"link_{i}_{g}"
            prob += buy[i, g] + sell[i, g] <= 1, f"nodoble_{i}_{g}"

        gasto = pulp.lpSum(precio[i] * buy[i, g] for i in ids)
        ingreso = pulp.lpSum((venta[i] if idx == 0 else precio[i]) * sell[i, g] for i in ids)
        anterior = banco0 if idx == 0 else bank[gws[idx - 1]]
        prob += bank[g] == anterior + ingreso - gasto, f"caja_{g}"

        usadas = pulp.lpSum(buy[i, g] for i in ids)
        libres = libres_hoy if idx == 0 else ft[g]
        if idx == 0 and frio:
            prob += hits[g] == 0, f"sinhits_{g}"
        else:
            prob += hits[g] >= usadas - libres, f"hits_{g}"

        if idx + 1 < len(gws):
            sig = gws[idx + 1]
            if idx == 0 and frio:
                # tras armar la plantilla se arranca con una transferencia libre
                prob += ft[sig] == 1, f"ftdin_{sig}"
            else:
                # Sobrante exacto en el optimo: hits[g] toma su cota inferior porque
                # esta penalizado, asi que libres - usadas + hits = max(0, libres - usadas).
                # Inflar hits para ganar una transferencia libre cuesta cuatro puntos y
                # ahorra como mucho cuatro: nunca es estrictamente mejor, no hay
                # incentivo espurio que rompa la equivalencia.
                prob += ft[sig] <= libres - usadas + hits[g] + 1, f"ftdin_{sig}"

    prob += _objetivo(ids, gws, xp_matrix, s, e, cap, hits, precio, rules, config)

    solver = pulp.PULP_CBC_CMD(msg=1 if config.solver_msg else 0,
                               timeLimit=config.time_limit, threads=1)
    prob.solve(solver)
    estado = pulp.LpStatus[prob.status]
    if estado not in ("Optimal",):
        raise Infeasible(_diagnose(state, pool, rules, banco0, estado))

    return _extract(prob, ids, gws, s, e, cap, buy, sell, hits, bank, estado, informe)


def _restricciones_plantilla(prob, ids, pos, club, s, e, cap, rules, g) -> None:
    prob += pulp.lpSum(s[i, g] for i in ids) == rules["size"], f"tam_{g}"
    for p, n in rules["composition"].items():
        prob += pulp.lpSum(s[i, g] for i in ids if pos[i] is p) == n, f"comp_{p.value}_{g}"

    prob += pulp.lpSum(e[i, g] for i in ids) == rules["starters"], f"xi_{g}"
    for i in ids:
        prob += e[i, g] <= s[i, g], f"xi_en_plantilla_{i}_{g}"
        prob += cap[i, g] <= e[i, g], f"cap_titular_{i}_{g}"
    prob += pulp.lpSum(cap[i, g] for i in ids) == 1, f"uncap_{g}"

    for p in (Position.GKP, Position.DEF, Position.MID, Position.FWD):
        del_pos = [i for i in ids if pos[i] is p]
        prob += pulp.lpSum(e[i, g] for i in del_pos) >= rules["formation_min"][p], f"fmin_{p.value}_{g}"
        prob += pulp.lpSum(e[i, g] for i in del_pos) <= rules["formation_max"][p], f"fmax_{p.value}_{g}"

    for c in sorted({club[i] for i in ids}):
        prob += (pulp.lpSum(s[i, g] for i in ids if club[i] == c) <= rules["max_per_club"],
                 f"club_{_slug(c)}_{g}")


def _objetivo(ids, gws, xp_matrix, s, e, cap, hits, precio, rules, config):
    terminos = []
    for g in gws:
        fila = xp_matrix[g]
        for i in ids:
            v = float(fila.get(i, 0.0))
            if v == 0.0:
                continue
            terminos.append(v * e[i, g])
            terminos.append(v * (rules["captain_multiplier"] - 1) * cap[i, g])
            terminos.append(config.bench_weight * v * (s[i, g] - e[i, g]))
        terminos.append(-rules["hit_cost"] * hits[g])
    # desempate: a igual xp prefiere la plantilla mas barata, que deja banco
    g0 = gws[0]
    terminos += [-config.tie_break * precio[i] * s[i, g0] for i in ids]
    return pulp.lpSum(terminos)


def _extract(prob, ids, gws, s, e, cap, buy, sell, hits, bank, estado, informe) -> Solution:
    on = lambda var: var.value() is not None and var.value() > 0.5
    return Solution(
        squad={g: tuple(i for i in ids if on(s[i, g])) for g in gws},
        starters={g: tuple(i for i in ids if on(e[i, g])) for g in gws},
        captain={g: next((i for i in ids if on(cap[i, g])), None) for g in gws},
        buys={g: tuple(i for i in ids if on(buy[i, g])) for g in gws},
        sells={g: tuple(i for i in ids if on(sell[i, g])) for g in gws},
        hits={g: int(round(hits[g].value() or 0)) for g in gws},
        bank={g: int(round(bank[g].value() or 0)) for g in gws},
        objective=float(pulp.value(prob.objective) or 0.0),
        status=estado, shortlist=informe,
    )


# ----------------------------------------------------------------- auxiliares

@dataclass(frozen=True, slots=True)
class _Blank:
    """Jugador de la plantilla sin fila en el mercado de esta jornada.

    Se declara aqui, y no se reutiliza `engine.state.Candidate`, porque el grafo
    de dependencias prohibe que `optimizer` importe de `engine`. Solo necesita
    los cinco atributos que el modelo lee.
    """
    element: int
    position: object
    team: str
    price: float
    xp: float = 0.0
    name: str = ""


def _pool(state) -> list:
    """Mercado + plantilla vigente. Un jugador en jornada en blanco no desaparece."""
    por_id = {c.element: c for c in state.candidates}
    if state.squad:
        for p in state.squad.players:
            if p.element not in por_id:
                por_id[p.element] = _Blank(element=p.element, position=p.position,
                                           team=p.team, price=p.price,
                                           name=f"blank_{p.element}")
    return sorted(por_id.values(), key=lambda c: c.element)


def _sale_values(state, pool, precio) -> dict:
    """Precio de venta FPL: de la subida solo se recupera la mitad (AC-WP006-003)."""
    venta = dict(precio)
    if not state.squad:
        return venta
    actual = {c.element: c.price for c in pool}
    for p in state.squad.players:
        if p.element not in actual:
            continue
        if p.purchase_price is None:
            venta[p.element] = to_tenths(actual[p.element])
        else:
            venta[p.element] = to_tenths(selling_price(p.purchase_price, actual[p.element]))
    return venta


def _precheck(pool, rules, presupuesto, en_plantilla) -> None:
    """Infactibilidades evidentes, detectadas antes de gastar tiempo de solver."""
    motivos = _estructural(pool, rules, presupuesto)
    if motivos:
        raise Infeasible(motivos)


def _estructural(pool, rules, presupuesto) -> list[str]:
    motivos: list[str] = []
    cuenta = Counter(c.position for c in pool)
    for p, n in rules["composition"].items():
        if cuenta.get(p, 0) < n:
            motivos.append(f"solo {cuenta.get(p, 0)} {p.value} en el mercado, hacen falta {n}")

    barato = 0
    for p, n in rules["composition"].items():
        precios = sorted(to_tenths(c.price) for c in pool if c.position is p)
        barato += sum(precios[:n])
    if motivos:
        return motivos
    if barato > presupuesto:
        motivos.append(f"la plantilla mas barata cuesta {to_millions(barato)}M y el "
                       f"presupuesto disponible es {to_millions(presupuesto)}M")

    clubes = Counter(c.team for c in pool)
    if sum(min(n, rules["max_per_club"]) for n in clubes.values()) < rules["size"]:
        motivos.append(f"con maximo {rules['max_per_club']} por club no se llegan a "
                       f"{rules['size']} jugadores: solo hay {len(clubes)} clubes")
    return motivos


def _diagnose(state, pool, rules, banco0, estado) -> list[str]:
    presupuesto = banco0 + sum(to_tenths(c.price) for c in pool
                               if state.squad and c.element in {p.element for p in state.squad.players})
    motivos = _estructural(pool, rules, presupuesto or banco0)
    if not motivos:
        motivos.append(f"el solver devolvio estado '{estado}' sin causa estructural evidente; "
                       f"mercado={len(pool)}, banco={to_millions(banco0)}M, "
                       f"transferencias libres={state.free_transfers}")
    return motivos


def _slug(texto: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in str(texto))
