"""WP-006: el horizonte rodante. Lo que separa a un optimizador competente de uno ingenuo.

Se prueba por separado de las restricciones porque son dos afirmaciones distintas:
aqui se verifica que el horizonte VALE, alla que la solucion es LEGAL.
"""
from __future__ import annotations

import pytest

from mova_fpl.engine.state import Candidate, State
from mova_fpl.optimizer import OptimizerConfig, build_xp_matrix, shortlist, solve
from mova_fpl.optimizer.horizon import DEFAULT_DECAY, summarize
from mova_fpl.rules import get as get_rules
from mova_fpl.rules.base import Position

RULES = get_rules("2025-26").SQUAD


def mercado(n_por_pos=(4, 8, 8, 5), precio_base=4.0, xp_base=2.0, clubes=8) -> list[Candidate]:
    """Mercado sintetico: barato, amplio y con clubes suficientes para la cuota."""
    out, e = [], 1
    for pos, n in zip((Position.GKP, Position.DEF, Position.MID, Position.FWD), n_por_pos):
        for k in range(n):
            out.append(Candidate(element=e, position=pos, team=f"C{e % clubes}",
                                 price=precio_base + 0.1 * k, xp=xp_base + 0.3 * k,
                                 name=f"{pos.value}{e}"))
            e += 1
    return out


def estado(cands, gw=1, squad=None, ft=1, bank=0.0, horizon_xp=None) -> State:
    return State(season="2025-26", gw=gw, candidates=tuple(cands), squad=squad,
                 free_transfers=ft, bank=bank, rules=RULES, horizon_xp=horizon_xp or {})


# ----------------------------------------------------- calendario y multiplicadores

def test_doble_jornada_duplica_el_xp_de_esa_jornada():
    c = mercado()[:1]
    m = build_xp_matrix(c, {(c[0].team, 5): 2}, gw=5, horizon=1)
    assert m[5][c[0].element] == pytest.approx(2 * c[0].xp)


def test_jornada_en_blanco_deja_el_xp_en_cero():
    c = mercado()[:1]
    m = build_xp_matrix(c, {}, gw=5, horizon=1)          # el club no aparece: no juega
    assert m[5][c[0].element] == 0.0


def test_el_descuento_no_toca_la_jornada_que_se_decide():
    c = mercado()[:1]
    sched = {(c[0].team, g): 1 for g in (5, 6, 7)}
    m = build_xp_matrix(c, sched, gw=5, horizon=3, decay=0.5)
    e = c[0].element
    assert m[5][e] == pytest.approx(c[0].xp)             # t=0 sin descontar
    assert m[6][e] == pytest.approx(c[0].xp * 0.5)
    assert m[7][e] == pytest.approx(c[0].xp * 0.25)


def test_horizonte_cubre_exactamente_las_jornadas_pedidas():
    c = mercado()[:3]
    sched = {(x.team, g): 1 for x in c for g in range(9, 13)}
    assert sorted(build_xp_matrix(c, sched, gw=9, horizon=4)) == [9, 10, 11, 12]
    assert set(summarize(build_xp_matrix(c, sched, gw=9, horizon=2))) == {9, 10}


@pytest.mark.parametrize("h,d", [(0, 0.9), (-1, 0.9), (3, 0.0), (3, 1.5)])
def test_parametros_invalidos_fallan_ruidosamente(h, d):
    with pytest.raises(ValueError):
        build_xp_matrix(mercado()[:1], {}, gw=1, horizon=h, decay=d)


# ----------------------------------------------------------------- AC-WP006-002

def _xp_realizado(secuencia, xp_matrix, rules) -> float:
    """xp acumulado de una secuencia de soluciones, con el coste de los hits."""
    total = 0.0
    for g, sol in secuencia:
        fila = xp_matrix[g]
        total += sum(fila.get(i, 0.0) for i in sol.starters[g])
        total += fila.get(sol.captain[g], 0.0) * (rules["captain_multiplier"] - 1)
        total -= rules["hit_cost"] * sol.hits[g]
    return total


def _rodar(cands, xp_matrix, gws, horizonte_solver, rules):
    """Simula el ciclo real: resuelve con el horizonte dado y ejecuta solo el primer paso."""
    from mova_fpl.rules.base import Squad, SquadPlayer
    atributos = {c.element: c for c in cands}
    squad, ft, bank, out = None, 1, 0.0, []
    for idx, g in enumerate(gws):
        ventana = {x: xp_matrix[x] for x in gws[idx:idx + horizonte_solver]}
        st = estado(cands, gw=g, squad=squad, ft=ft, bank=bank)
        sol = solve(st, ventana, OptimizerConfig(horizon=len(ventana), top_k=0,
                                                 bench_weight=0.0, time_limit=20))
        out.append((g, sol))
        players = tuple(SquadPlayer(element=i, position=atributos[i].position,
                                    team=atributos[i].team, price=atributos[i].price)
                        for i in sol.squad[g])
        squad = Squad(players=players, starters=sol.starters[g], captain=sol.captain[g],
                      bank=sol.bank[g] / 10.0)
        bank = sol.bank[g] / 10.0
        ft = 1 if idx == 0 else min(rules["max_free_transfers"],
                                    max(0, ft - len(sol.buys[g])) + 1)
    return out


def test_horizonte_3_no_es_peor_que_horizonte_1_sobre_el_mismo_tramo():
    """AC-WP006-002. Es la afirmacion central del workpack, y no se supone: se mide.

    El mercado se disena para que importe: hay jugadores que solo puntuan en la
    tercera jornada. Un optimizador miope no los ve venir; uno con horizonte si.
    """
    cands = mercado(n_por_pos=(4, 10, 10, 6), precio_base=4.0, xp_base=1.0, clubes=10)
    gws = [10, 11, 12]
    # todos juegan siempre, salvo que a un club le llega su gran jornada al final
    sched = {(c.team, g): 1 for c in cands for g in gws}
    base = build_xp_matrix(cands, sched, gw=10, horizon=3, decay=1.0)
    estrellas = {c.element for c in cands if c.team == "C3"}
    for e in estrellas:
        base[10][e], base[11][e], base[12][e] = 0.1, 0.1, 12.0

    largo = _xp_realizado(_rodar(cands, base, gws, 3, RULES), base, RULES)
    corto = _xp_realizado(_rodar(cands, base, gws, 1, RULES), base, RULES)
    # ESTRICTAMENTE mejor, no solo "no peor": con >= el test podria volverse vacuo
    # si el horizonte dejara de influir y nadie se enteraria. Medido: 141.2 vs 137.2,
    # porque el largo compra una estrella en la GW10 y llega a la GW12 sin pagar hit.
    assert largo > corto


# ----------------------------------------------------------------- AC-WP006-006

def test_el_prefiltro_nunca_expulsa_a_la_plantilla_actual():
    """Si el recorte borra a un titular, el modelo no puede decidir NO venderlo."""
    cands = mercado(n_por_pos=(6, 20, 20, 12))
    xp = build_xp_matrix(cands, {(c.team, 1): 1 for c in cands}, gw=1, horizon=1)
    peores = [c.element for c in sorted(cands, key=lambda c: c.xp)[:5]]
    recorte, informe = shortlist(cands, xp, keep_ids=peores, top_k=3, cheapest=0)
    assert set(peores) <= {c.element for c in recorte}
    assert informe.forzados > 0
    assert informe.kept < informe.total


def test_el_prefiltro_declara_cuanto_recorto():
    cands = mercado(n_por_pos=(6, 20, 20, 12))
    xp = build_xp_matrix(cands, {(c.team, 1): 1 for c in cands}, gw=1, horizon=1)
    _, informe = shortlist(cands, xp, top_k=5, cheapest=2)
    assert 0 < informe.ratio < 1
    assert "shortlist" in str(informe)


def test_top_k_cero_desactiva_el_recorte():
    cands = mercado(n_por_pos=(6, 20, 20, 12))
    xp = build_xp_matrix(cands, {(c.team, 1): 1 for c in cands}, gw=1, horizon=1)
    recorte, informe = shortlist(cands, xp, top_k=0)
    assert informe.kept == informe.total == len(recorte)


def test_decay_por_defecto_es_el_documentado():
    assert 0 < DEFAULT_DECAY < 1
