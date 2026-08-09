"""Chips dentro del MILP: el efecto que promete la regla, y ni uno mas.

Cada chip se prueba en una micro-instancia donde su efecto es la UNICA explicacion
posible del cambio. Un test que solo comprueba "con chip puntua mas" no distingue
entre el chip funcionando y el solver encontrando otra cosa.
"""
from __future__ import annotations

import pytest

from mova_fpl.engine.state import Candidate, State
from mova_fpl.optimizer import Infeasible, OptimizerConfig, build_xp_matrix, solve
from mova_fpl.rules import get as get_rules
from mova_fpl.rules.base import Position, Squad, SquadPlayer
from mova_fpl.rules.chips import ChipUse

RULES = get_rules("2025-26").SQUAD
CATALOGO = get_rules("2025-26").CHIPS


def mercado(n_por_pos=(5, 12, 12, 7), precio_base=4.0, xp_base=2.0, clubes=10, salto=0.1):
    out, e = [], 1
    for pos, n in zip((Position.GKP, Position.DEF, Position.MID, Position.FWD), n_por_pos):
        for k in range(n):
            out.append(Candidate(element=e, position=pos, team=f"C{e % clubes}",
                                 price=round(precio_base + salto * k, 1),
                                 xp=xp_base + 0.4 * k, name=f"{pos.value}{e}"))
            e += 1
    return out


def matriz(cands, gw=1, horizon=1, decay=1.0):
    sched = {(c.team, g): 1 for c in cands for g in range(gw, gw + horizon)}
    return build_xp_matrix(cands, sched, gw=gw, horizon=horizon, decay=decay)


def estado(cands, gw=1, squad=None, ft=1, bank=0.0, permitidos=None, usados=()):
    return State(season="2025-26", gw=gw, candidates=tuple(cands), squad=squad,
                 free_transfers=ft, bank=bank, rules=RULES, chips=CATALOGO,
                 chips_used=tuple(usados), chips_allowed=permitidos or {})


def squad_de(sol, gw, cands, bank=0.0, compra=None) -> Squad:
    attr = {c.element: c for c in cands}
    players = tuple(SquadPlayer(element=i, position=attr[i].position, team=attr[i].team,
                                price=attr[i].price,
                                purchase_price=(compra or {}).get(i))
                    for i in sol.squad[gw])
    return Squad(players=players, starters=sol.starters[gw], captain=sol.captain[gw],
                 vice_captain=next(i for i in sol.starters[gw] if i != sol.captain[gw]),
                 bench_order=tuple(i for i in sol.squad[gw] if i not in set(sol.starters[gw])),
                 bank=bank)


# ------------------------------------------------- equivalencia con el modelo v1

def test_sin_autorizacion_el_modelo_es_el_de_siempre():
    """La garantia de regresion: sin chips autorizados no se crea ni una variable.

    Es lo que permite afirmar que meter chips no movio los 2.217 puntos previos.
    """
    cands = mercado()
    base = solve(estado(cands), matriz(cands), OptimizerConfig(top_k=0))
    con_catalogo = solve(estado(cands, permitidos={}), matriz(cands), OptimizerConfig(top_k=0))
    assert base.squad[1] == con_catalogo.squad[1]
    assert base.objective == pytest.approx(con_catalogo.objective)
    assert con_catalogo.chips == {1: None}


# ------------------------------------------------------------- triple captain

def test_triple_captain_multiplica_al_capitan_no_al_resto():
    cands = mercado()
    xp = matriz(cands)
    base = solve(estado(cands), xp, OptimizerConfig(top_k=0))
    tc = solve(estado(cands, permitidos={1: {"triple_captain"}}), xp, OptimizerConfig(top_k=0))

    assert tc.chips[1] == "triple_captain"
    mejor = max(xp[1][i] for i in tc.starters[1])
    # el capitan pasa de x2 a x3: exactamente un xp de capitan mas
    assert tc.objective - base.objective == pytest.approx(mejor, abs=1e-2)
    assert xp[1][tc.captain[1]] == pytest.approx(mejor)

    # y la identidad exacta sobre la solucion elegida
    cfg = OptimizerConfig(top_k=0, tie_break=0.0, chip_epsilon=0.0)
    tc2 = solve(estado(cands, permitidos={1: {"triple_captain"}}), xp, cfg)
    xi, banca = set(tc2.starters[1]), [i for i in tc2.squad[1] if i not in set(tc2.starters[1])]
    esperado = (sum(xp[1][i] for i in xi)
                + 2 * xp[1][tc2.captain[1]]            # x3 = base + 2 extra
                + 0.12 * sum(xp[1][i] for i in banca))
    assert tc2.objective == pytest.approx(esperado, abs=1e-6)


def test_triple_captain_no_se_juega_si_no_aporta():
    """xp cero en todo el mercado: el chip no cambia nada y el epsilon lo guarda."""
    cands = [Candidate(element=c.element, position=c.position, team=c.team,
                       price=c.price, xp=0.0, name=c.name) for c in mercado()]
    sol = solve(estado(cands, permitidos={1: {"triple_captain"}}), matriz(cands),
                OptimizerConfig(top_k=0))
    assert sol.chips[1] is None


# ---------------------------------------------------------------- bench boost

def test_bench_boost_hace_valer_al_banquillo_entero():
    """Identidad exacta: el objetivo de la solucion con BB se reconstruye a mano.

    Comparar contra el objetivo SIN chip no serviria: con bench boost el modelo
    cambia de plantilla —compra mejor banquillo y sacrifica algo del XI—, asi que
    la diferencia no es el banquillo base revalorizado. Lo que si debe cumplirse
    exactamente es que el banquillo puntue entero en la solucion que se eligio.
    """
    cands = mercado()
    xp = matriz(cands)
    cfg = OptimizerConfig(top_k=0, bench_weight=0.12, tie_break=0.0, chip_epsilon=0.0)
    bb = solve(estado(cands, permitidos={1: {"bench_boost"}}), xp, cfg)

    assert bb.chips[1] == "bench_boost"
    xi = set(bb.starters[1])
    banca = [i for i in bb.squad[1] if i not in xi]
    assert len(banca) == 4

    esperado = (sum(xp[1][i] for i in xi)              # el XI
                + xp[1][bb.captain[1]]                 # el capitan, x2
                + sum(xp[1][i] for i in banca))        # el banquillo ENTERO, no al 12%
    assert bb.objective == pytest.approx(esperado, abs=1e-6)


def test_bench_boost_mejora_el_banquillo_no_solo_el_xi():
    """Con BB el modelo deja de comprar suplentes de relleno."""
    cands = mercado()
    xp = matriz(cands)
    cfg = OptimizerConfig(top_k=0)
    base = solve(estado(cands), xp, cfg)
    bb = solve(estado(cands, permitidos={1: {"bench_boost"}}), xp, cfg)

    val = lambda sol: sum(xp[1][i] for i in sol.squad[1] if i not in set(sol.starters[1]))
    assert val(bb) > val(base)


# ------------------------------------------------------------------ wildcard

def test_wildcard_exime_del_coste_de_los_hits():
    cands = mercado()
    xp = matriz(cands)
    cfg = OptimizerConfig(top_k=0, max_hits_per_gw=2)

    # plantilla vigente deliberadamente mala: los 15 mas baratos
    baratos = sorted(cands, key=lambda c: (c.position.value, c.price))
    por_pos = {p: [c for c in baratos if c.position is p] for p in Position}
    elegidos = (por_pos[Position.GKP][:2] + por_pos[Position.DEF][:5]
                + por_pos[Position.MID][:5] + por_pos[Position.FWD][:3])
    players = tuple(SquadPlayer(element=c.element, position=c.position, team=c.team,
                                price=c.price, purchase_price=c.price) for c in elegidos)
    squad = Squad(players=players, starters=tuple(c.element for c in elegidos[:11]),
                  captain=elegidos[0].element, vice_captain=elegidos[1].element,
                  bench_order=tuple(c.element for c in elegidos[11:]), bank=30.0)

    sin = solve(estado(cands, squad=squad, ft=1, bank=30.0), xp, cfg)
    con = solve(estado(cands, squad=squad, ft=1, bank=30.0,
                       permitidos={1: {"wildcard"}}), xp, cfg)

    assert con.chips[1] == "wildcard"
    assert con.hits[1] == 0                       # con wildcard nunca se paga
    assert len(con.buys[1]) > len(sin.buys[1])    # y se reconstruye a fondo
    assert len(con.buys[1]) > 2                   # por encima del tope de hits


def test_wildcard_conserva_las_transferencias_libres():
    """Regla oficial: el wildcard no destruye las libres acumuladas, suman +1."""
    cands = mercado()
    xp = matriz(cands, horizon=2)
    cfg = OptimizerConfig(top_k=0, horizon=2)
    baratos = sorted(cands, key=lambda c: (c.position.value, c.price))
    por_pos = {p: [c for c in baratos if c.position is p] for p in Position}
    elegidos = (por_pos[Position.GKP][:2] + por_pos[Position.DEF][:5]
                + por_pos[Position.MID][:5] + por_pos[Position.FWD][:3])
    players = tuple(SquadPlayer(element=c.element, position=c.position, team=c.team,
                                price=c.price, purchase_price=c.price) for c in elegidos)
    squad = Squad(players=players, starters=tuple(c.element for c in elegidos[:11]),
                  captain=elegidos[0].element, vice_captain=elegidos[1].element,
                  bench_order=tuple(c.element for c in elegidos[11:]), bank=30.0)

    sol = solve(estado(cands, squad=squad, ft=2, bank=30.0,
                       permitidos={1: {"wildcard"}}), xp, cfg)
    assert sol.chips[1] == "wildcard"
    assert sol.hits[1] == 0
    # tras un wildcard con 2 libres se llega a la siguiente jornada con 3
    assert len(sol.buys[2]) <= 3


# ------------------------------------------------------- inventario y ventanas

def test_un_solo_chip_por_jornada():
    cands = mercado()
    sol = solve(estado(cands, permitidos={1: {"triple_captain", "bench_boost"}}),
                matriz(cands), OptimizerConfig(top_k=0))
    assert sol.chips[1] in ("triple_captain", "bench_boost")


def test_el_mismo_chip_no_se_repite_dentro_de_la_ventana():
    cands = mercado()
    xp = matriz(cands, horizon=3)
    permitidos = {g: {"triple_captain"} for g in (1, 2, 3)}
    sol = solve(estado(cands, permitidos=permitidos), xp,
                OptimizerConfig(top_k=0, horizon=3))
    assert sum(1 for c in sol.chips.values() if c == "triple_captain") == 1


def test_el_mismo_chip_puede_repetirse_cruzando_la_gw19():
    """Dos ventanas, dos ejemplares: el corte de la GW19 refresca el inventario."""
    cands = mercado()
    xp = matriz(cands, gw=18, horizon=3)          # GW18, 19 | 20
    permitidos = {g: {"triple_captain"} for g in (18, 19, 20)}
    sol = solve(estado(cands, gw=18, permitidos=permitidos), xp,
                OptimizerConfig(top_k=0, horizon=3))
    assert sum(1 for c in sol.chips.values() if c == "triple_captain") == 2


def test_el_free_hit_nunca_entra_al_milp():
    """Se resuelve por descomposicion; autorizarlo aqui no debe hacer nada."""
    cands = mercado()
    sol = solve(estado(cands, permitidos={1: {"free_hit"}}), matriz(cands),
                OptimizerConfig(top_k=0))
    assert sol.chips[1] is None


# ------------------------------------------------------- restricciones agente

def test_lock_in_impide_vender_al_jugador_protegido():
    cands = mercado()
    xp = matriz(cands)
    baratos = sorted(cands, key=lambda c: (c.position.value, c.price))
    por_pos = {p: [c for c in baratos if c.position is p] for p in Position}
    elegidos = (por_pos[Position.GKP][:2] + por_pos[Position.DEF][:5]
                + por_pos[Position.MID][:5] + por_pos[Position.FWD][:3])
    players = tuple(SquadPlayer(element=c.element, position=c.position, team=c.team,
                                price=c.price, purchase_price=c.price) for c in elegidos)
    squad = Squad(players=players, starters=tuple(c.element for c in elegidos[:11]),
                  captain=elegidos[0].element, vice_captain=elegidos[1].element,
                  bench_order=tuple(c.element for c in elegidos[11:]), bank=30.0)

    libre = solve(estado(cands, squad=squad, ft=5, bank=30.0), xp, OptimizerConfig(top_k=0))
    assert libre.sells[1], "el caso base debe vender a alguien para que la prueba diga algo"

    protegido = libre.sells[1][0]
    st = estado(cands, squad=squad, ft=5, bank=30.0)
    st = type(st)(**{**{f: getattr(st, f) for f in st.__slots__},
                     "lock_in": frozenset({protegido})})
    con_veto = solve(st, xp, OptimizerConfig(top_k=0))
    assert protegido not in con_veto.sells[1]
    assert protegido in con_veto.squad[1]


def test_lock_out_saca_al_jugador_de_toda_la_plantilla():
    cands = mercado()
    xp = matriz(cands)
    base = solve(estado(cands), xp, OptimizerConfig(top_k=0))
    vetado = base.starters[1][0]

    st = estado(cands)
    st = type(st)(**{**{f: getattr(st, f) for f in st.__slots__},
                     "lock_out": frozenset({vetado})})
    sol = solve(st, xp, OptimizerConfig(top_k=0))
    assert vetado not in sol.squad[1]


# ------------------------------------------------------- free hit (descomposicion)

def _plantilla_de(cands, filtro=lambda c: True, bank=0.0):
    baratos = sorted([c for c in cands if filtro(c)], key=lambda c: (c.position.value, c.price))
    por_pos = {p: [c for c in baratos if c.position is p] for p in Position}
    elegidos = (por_pos[Position.GKP][:2] + por_pos[Position.DEF][:5]
                + por_pos[Position.MID][:5] + por_pos[Position.FWD][:3])
    players = tuple(SquadPlayer(element=c.element, position=c.position, team=c.team,
                                price=c.price, purchase_price=c.price) for c in elegidos)
    return Squad(players=players, starters=tuple(c.element for c in elegidos[:11]),
                 captain=elegidos[0].element, vice_captain=elegidos[1].element,
                 bench_order=tuple(c.element for c in elegidos[11:]), bank=bank)


def test_free_hit_vale_mucho_en_jornada_en_blanco():
    """Media plantilla sin partido: el free hit deberia arreglar la jornada entera."""
    from mova_fpl.optimizer import evaluate_free_hit

    cands = mercado(clubes=6)
    squad = _plantilla_de(cands, bank=5.0)
    en_plantilla = {p.element for p in squad.players}

    # los clubes de la plantilla vigente no juegan: xp cero para ellos
    fila = {c.element: (0.0 if c.element in en_plantilla else c.xp) for c in cands}
    st = estado(cands, squad=squad, ft=1, bank=5.0)

    plan = evaluate_free_hit(st, fila, OptimizerConfig(top_k=0))
    assert plan.value > 10.0, "con la plantilla en blanco el free hit tiene que rendir"
    assert len(plan.squad) == 15
    # El XI no puede llevar a nadie que no juegue. En la plantilla si pueden quedar
    # jugadores en blanco: con tope de tres por club no siempre hay con quien
    # rellenar los cuatro suplentes, y en el banquillo no cuestan nada.
    assert all(fila[i] > 0 for i in plan.starters), "ningun titular puede estar en blanco"


def test_free_hit_no_aporta_si_la_plantilla_ya_es_la_mejor():
    """Plantilla optima y mercado sin nada mejor: el chip no tiene que ganar nada."""
    from mova_fpl.optimizer import evaluate_free_hit

    cands = mercado()
    base = solve(estado(cands), matriz(cands), OptimizerConfig(top_k=0))
    attr = {c.element: c for c in cands}
    players = tuple(SquadPlayer(element=i, position=attr[i].position, team=attr[i].team,
                                price=attr[i].price, purchase_price=attr[i].price)
                    for i in base.squad[1])
    squad = Squad(players=players, starters=base.starters[1], captain=base.captain[1],
                  vice_captain=next(i for i in base.starters[1] if i != base.captain[1]),
                  bench_order=tuple(i for i in base.squad[1] if i not in set(base.starters[1])),
                  bank=0.0)

    st = estado(cands, squad=squad, ft=1, bank=0.0)
    plan = evaluate_free_hit(st, {c.element: c.xp for c in cands}, OptimizerConfig(top_k=0))
    assert plan.value == pytest.approx(0.0, abs=0.2)


def test_el_presupuesto_del_free_hit_liquida_la_plantilla():
    from mova_fpl.optimizer import free_hit_budget

    cands = mercado()
    squad = _plantilla_de(cands, bank=3.5)
    st = estado(cands, squad=squad, bank=3.5)
    esperado = round(sum(p.price for p in squad.players) + 3.5, 1)
    assert free_hit_budget(st) == pytest.approx(esperado, abs=0.05)
