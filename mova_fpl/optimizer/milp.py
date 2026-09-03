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

SI (chips): wildcard, bench boost y triple captain como variables binarias, solo
en las jornadas que el planificador AUTORICE via `state.chips_allowed`. Autorizar
no es obligar: el optimizador los juega si le convienen. Con la autorizacion vacia
el modelo es identico al de v1, byte a byte.

NO: free hit — su semantica (la plantilla revierte a la jornada siguiente) rompe
la restriccion de enlace s[i,g+1] = s[i,g] + buy - sell, y modelarlo exigiria
duplicar las variables de plantilla. Se resuelve fuera, por descomposicion, en
`optimizer/freehit.py`: una jornada desacoplada se calcula exacto con un solve
aparte. Es mas simple Y mas correcto que meterlo al modelo grande.

NO: precio futuro de los jugadores, vicecapitan (solo importa si el capitan no
juega; se asigna despues por xp), y sustituciones automaticas (el banquillo entra
al objetivo con un peso, no como decision).

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

#: chips que el MILP sabe modelar. El free hit se resuelve por descomposicion.
CHIPS_MODELADOS = ("wildcard", "bench_boost", "triple_captain")


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
    #: valor futuro de conservar una transferencia. Cero reproduce produccion.
    transfer_penalty: float = 0.0
    #: valor de continuación de cada FT disponible después del último GW modelado.
    #: Cero reproduce producción; debe ser menor al coste de un hit para no crear hits.
    terminal_free_transfer_value: float = 0.0
    #: robustez epistemica: solo grava comprar/vender cuando la proyeccion es
    #: incierta; no castiga la varianza deportiva de quien ya esta elegido.
    uncertainty_transfer_weight: float = 0.0
    tie_break: float = 1e-6           # a igual xp, prefiere plantilla mas barata
    #: penalizacion simbolica por jugar un chip. Evita que el modelo queme un chip
    #: que no aporta nada: ante empate, prefiere guardarlo. No expresa su coste de
    #: oportunidad real — eso vive en el planificador, que si ve la temporada entera.
    chip_epsilon: float = 1e-3
    solver_msg: bool = False


@dataclass(frozen=True, slots=True)
class FirstStage:
    """Decisión de la jornada actual que permanece fija entre escenarios.

    El resto del horizonte queda libre para representar recourse: después de
    observar un escenario, cada trayectoria puede volver a optimizar sus
    transferencias futuras sin reescribir la acción ya tomada hoy.
    """
    squad: tuple[int, ...]
    starters: tuple[int, ...] = ()
    captain: int | None = None


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
    chips: dict            # gw -> nombre del chip jugado, o None
    objective: float
    status: str
    shortlist: object
    terminal_free_transfers: int | None = None


# --------------------------------------------------------------------- modelo

def solve(state, xp_matrix: dict, config: OptimizerConfig | None = None, *,
          first_stage: FirstStage | None = None) -> Solution:
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
    terminal_value = float(config.terminal_free_transfer_value)
    if not 0.0 <= terminal_value < float(rules["hit_cost"]):
        raise ValueError("terminal_free_transfer_value debe estar entre 0 y hit_cost")

    pool = _pool(state)
    en_plantilla = {p.element for p in state.squad.players} if state.squad else set()
    conservar = en_plantilla | (set(first_stage.squad) if first_stage else set())
    pool, informe = shortlist(pool, xp_matrix, keep_ids=conservar,
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

    chip = _chip_vars(prob, gws, state)

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
        # Con wildcard las transferencias son gratis e ilimitadas: la cota de hits
        # deja de restringir cuantas se pueden hacer.
        indulto = rules["size"] * chip.get(("wildcard", g), 0)
        if idx == 0 and frio:
            prob += hits[g] == 0, f"sinhits_{g}"
        else:
            prob += hits[g] >= usadas - libres - indulto, f"hits_{g}"

        if idx + 1 < len(gws):
            sig = gws[idx + 1]
            if idx == 0 and frio:
                # tras armar la plantilla se arranca con una transferencia libre
                prob += ft[sig] == 1, f"ftdin_{sig}"
            else:
                # El wildcard NO destruye las libres acumuladas: se conservan y suman
                # una. Sin wildcard esta cota es redundante (la de abajo es mas
                # ajustada); con wildcard es exactamente la regla oficial.
                prob += ft[sig] <= libres + 1, f"ftmax_{sig}"
                # Sobrante exacto en el optimo: hits[g] toma su cota inferior porque
                # esta penalizado, asi que libres - usadas + hits = max(0, libres - usadas).
                # Inflar hits para ganar una transferencia libre cuesta cuatro puntos y
                # ahorra como mucho cuatro: nunca es estrictamente mejor, no hay
                # incentivo espurio que rompa la equivalencia.
                prob += (ft[sig] <= libres - usadas + hits[g] + 1 + indulto,
                         f"ftdin_{sig}")

    terminal_ft = None
    if terminal_value:
        last = gws[-1]
        terminal_ft = pulp.LpVariable(
            "ft_terminal", lowBound=1, upBound=rules["max_free_transfers"],
            cat="Integer",
        )
        libres = libres_hoy if len(gws) == 1 else ft[last]
        usadas = pulp.lpSum(buy[i, last] for i in ids)
        indulto = rules["size"] * chip.get(("wildcard", last), 0)
        prob += terminal_ft <= libres + 1, "ft_terminal_max"
        prob += (
            terminal_ft <= libres - usadas + hits[last] + 1 + indulto,
            "ft_terminal_dynamics",
        )

    _restricciones_agente(prob, ids, gws, state, s, sell, en_plantilla)
    if first_stage is not None:
        _fijar_primera_etapa(prob, first_stage, ids, gws[0], s, e, cap, rules)
    prob += _objetivo(prob, ids, gws, xp_matrix, s, e, cap, buy, sell, hits, chip,
                      precio, rules, config, getattr(state, "horizon_sd", None) or {}, frio,
                      terminal_ft)

    solver = pulp.PULP_CBC_CMD(msg=1 if config.solver_msg else 0,
                               timeLimit=config.time_limit, threads=1)
    prob.solve(solver)
    estado = pulp.LpStatus[prob.status]
    if estado not in ("Optimal",):
        raise Infeasible(_diagnose(state, pool, rules, banco0, estado))

    return _extract(
        prob, ids, gws, s, e, cap, buy, sell, hits, bank, chip, estado, informe,
        terminal_ft,
    )


def _fijar_primera_etapa(prob, stage: FirstStage, ids: list[int], gw: int,
                         s: dict, e: dict, cap: dict, rules: dict) -> None:
    """Fija solo la acción irreversible de hoy; el futuro conserva recourse."""
    universe = set(ids)
    squad = set(int(value) for value in stage.squad)
    starters = set(int(value) for value in stage.starters)
    if len(stage.squad) != rules["size"] or len(squad) != rules["size"]:
        raise ValueError("first_stage.squad debe contener la plantilla completa sin duplicados")
    if not squad <= universe:
        raise ValueError("first_stage contiene jugadores fuera del mercado")
    if stage.starters:
        if (len(stage.starters) != rules["starters"]
                or len(starters) != rules["starters"] or not starters <= squad):
            raise ValueError("first_stage.starters no es un XI válido dentro del squad")
    if stage.captain is not None:
        if int(stage.captain) not in (starters if stage.starters else squad):
            raise ValueError("first_stage.captain debe pertenecer a la etapa fijada")

    for element in ids:
        prob += s[element, gw] == int(element in squad), f"fix_s_{element}_{gw}"
        if stage.starters:
            prob += e[element, gw] == int(element in starters), f"fix_e_{element}_{gw}"
        if stage.captain is not None:
            prob += cap[element, gw] == int(element == int(stage.captain)), \
                f"fix_c_{element}_{gw}"


def _chip_vars(prob, gws, state) -> dict:
    """Binarias de chip, solo donde el planificador autorizo. {(chip, gw): var}.

    Sin autorizaciones no crea ni una variable: el modelo queda identico al de v1.
    Esa equivalencia es la que permite verificar por regresion que meter chips no
    movio nada de lo anterior.
    """
    permitido = getattr(state, "chips_allowed", None) or {}
    if not permitido:
        return {}

    chip: dict = {}
    for g in gws:
        for c in sorted(set(permitido.get(g, ())) & set(CHIPS_MODELADOS)):
            chip[c, g] = pulp.LpVariable(f"chip_{c}_{g}", cat="Binary")

    for g in gws:                                    # un solo chip por jornada
        del_gw = [v for (c, gg), v in chip.items() if gg == g]
        if len(del_gw) > 1:
            prob += pulp.lpSum(del_gw) <= 1, f"unchip_{g}"

    # Un ejemplar de cada chip por ventana. Se agrupa por ventana y no por horizonte
    # porque un horizonte largo puede cruzar el corte de la GW19, y ahi el mismo
    # chip vuelve a estar disponible legalmente.
    catalogo = getattr(state, "chips", None)
    for c in CHIPS_MODELADOS:
        gws_c = [g for (cc, g) in chip if cc == c]
        if len(gws_c) <= 1:
            continue
        grupos: dict = {}
        for g in gws_c:
            w = catalogo.window_for(g) if catalogo is not None else None
            grupos.setdefault(w.name if w else "unica", []).append(g)
        for nombre, gs in grupos.items():
            if len(gs) > 1:
                prob += (pulp.lpSum(chip[c, g] for g in gs) <= 1,
                         f"invent_{c}_{_slug(nombre)}")
    return chip


def _restricciones_agente(prob, ids, gws, state, s, sell, en_plantilla) -> None:
    """Vetos que un agente externo puede imponer sobre la plantilla.

    `lock_in`  — no vender en la jornada que se decide (p. ej. sube de precio).
    `lock_out` — no puede estar en plantilla en todo el horizonte (p. ej. lesion).

    Son restricciones DURAS: si contradicen las reglas, el problema sale infactible
    con su diagnostico. Un agente que se equivoca hace ruido, no dana en silencio.
    """
    dentro = frozenset(getattr(state, "lock_in", ()) or ())
    fuera = frozenset(getattr(state, "lock_out", ()) or ())
    g0 = gws[0]
    for i in dentro & set(ids) & set(en_plantilla):
        prob += sell[i, g0] == 0, f"lockin_{i}"
    for i in fuera & set(ids):
        for g in gws:
            prob += s[i, g] == 0, f"lockout_{i}_{g}"


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


def _objetivo(prob, ids, gws, xp_matrix, s, e, cap, buy, sell, hits, chip, precio,
              rules, config, sd_matrix, cold_start, terminal_ft=None):
    """Puntos esperados del horizonte, descontados, menos el coste de los hits.

    Los chips entran como productos de binarias, linealizados. Para el bench boost
    y el triple captain basta con las cotas superiores del producto: el objetivo
    los empuja hacia arriba (coeficiente positivo), asi que el optimo las satura.
    La tercera desigualdad de la linealizacion clasica seria redundante aqui.

    Recibe `prob` porque las variables auxiliares del producto necesitan colgar sus
    restricciones del mismo problema.
    """
    terminos = []
    for g in gws:
        fila = xp_matrix[g]
        tc = chip.get(("triple_captain", g))
        bb = chip.get(("bench_boost", g))
        for i in ids:
            v = float(fila.get(i, 0.0))
            if v == 0.0:
                continue
            terminos.append(v * e[i, g])
            terminos.append(v * (rules["captain_multiplier"] - 1) * cap[i, g])
            terminos.append(config.bench_weight * v * (s[i, g] - e[i, g]))

            if tc is not None:
                # y = cap AND tc  ->  el capitan pasa de x2 a x3
                y = pulp.LpVariable(f"tcx_{i}_{g}", lowBound=0, upBound=1)
                prob += y <= cap[i, g], f"tcx_a_{i}_{g}"
                prob += y <= tc, f"tcx_b_{i}_{g}"
                terminos.append(v * y)
            if bb is not None:
                # z = bb AND (en plantilla, fuera del XI) -> el suplente puntua entero
                z = pulp.LpVariable(f"bbx_{i}_{g}", lowBound=0, upBound=1)
                prob += z <= bb, f"bbx_a_{i}_{g}"
                prob += z <= s[i, g] - e[i, g], f"bbx_b_{i}_{g}"
                terminos.append((1.0 - config.bench_weight) * v * z)

        terminos.append(-rules["hit_cost"] * hits[g])
        if not (cold_start and g == gws[0]):
            if config.transfer_penalty:
                terminos.append(-float(config.transfer_penalty)
                                 * pulp.lpSum(buy[i, g] for i in ids))
            if config.uncertainty_transfer_weight:
                sd = sd_matrix.get(g, {})
                terminos.append(-0.5 * float(config.uncertainty_transfer_weight)
                                 * pulp.lpSum(float(sd.get(i, 0.0))
                                              * (buy[i, g] + sell[i, g]) for i in ids))
    # ante empate, guardar el chip antes que quemarlo
    terminos += [-config.chip_epsilon * v for v in chip.values()]
    if terminal_ft is not None:
        terminos.append(float(config.terminal_free_transfer_value) * terminal_ft)
    # desempate: a igual xp prefiere la plantilla mas barata, que deja banco
    g0 = gws[0]
    terminos += [-config.tie_break * precio[i] * s[i, g0] for i in ids]
    return pulp.lpSum(terminos)


def _extract(prob, ids, gws, s, e, cap, buy, sell, hits, bank, chip, estado, informe,
             terminal_ft=None) -> Solution:
    on = lambda var: var.value() is not None and var.value() > 0.5
    jugado = {g: next((c for (c, gg), v in chip.items() if gg == g and on(v)), None)
              for g in gws}
    return Solution(
        squad={g: tuple(i for i in ids if on(s[i, g])) for g in gws},
        starters={g: tuple(i for i in ids if on(e[i, g])) for g in gws},
        captain={g: next((i for i in ids if on(cap[i, g])), None) for g in gws},
        buys={g: tuple(i for i in ids if on(buy[i, g])) for g in gws},
        sells={g: tuple(i for i in ids if on(sell[i, g])) for g in gws},
        hits={g: int(round(hits[g].value() or 0)) for g in gws},
        bank={g: int(round(bank[g].value() or 0)) for g in gws},
        chips=jugado,
        objective=float(pulp.value(prob.objective) or 0.0),
        status=estado, shortlist=informe,
        terminal_free_transfers=(
            int(round(terminal_ft.value())) if terminal_ft is not None else None
        ),
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
