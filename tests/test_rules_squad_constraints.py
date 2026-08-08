"""WP-002 / AC-WP002-003,-004,-005: plantilla, sustituciones automaticas y diff."""
from __future__ import annotations

import pytest

from mova_fpl.rules import Position, Squad, SquadPlayer, get
from mova_fpl.rules.autosubs import apply_auto_subs, effective_captain
from mova_fpl.rules.bps import CAMBIOS_2026_27
from mova_fpl.rules.diff import compute
from mova_fpl.rules.market import (accumulate_free_transfers, selling_price,
                                   squad_value, transfer_cost)
from mova_fpl.rules.squad import validate_squad

R = get("2025-26").SQUAD
P = Position


def build(comp=(2, 5, 5, 3), clubs=None, price=5.0, n=15):
    """Plantilla sintetica valida por defecto."""
    pos = [P.GKP] * comp[0] + [P.DEF] * comp[1] + [P.MID] * comp[2] + [P.FWD] * comp[3]
    pos = pos[:n]
    clubs = clubs or [f"C{i // 3}" for i in range(len(pos))]
    return tuple(SquadPlayer(element=i + 1, position=p, team=clubs[i], price=price)
                 for i, p in enumerate(pos))


def lineup(players, formation=(1, 4, 4, 2)):
    xi, need = [], {P.GKP: formation[0], P.DEF: formation[1], P.MID: formation[2], P.FWD: formation[3]}
    for p in players:
        if need.get(p.position, 0) > 0:
            xi.append(p.element)
            need[p.position] -= 1
    bench = [p.element for p in players if p.element not in xi]
    return tuple(xi), tuple(bench)


def valid_squad(**kw):
    players = build(**kw)
    xi, bench = lineup(players)
    return Squad(players=players, starters=xi, captain=xi[1], vice_captain=xi[2], bench_order=bench)


# --------------------------------------------------- AC-WP002-003

def test_plantilla_valida_no_tiene_violaciones():
    assert validate_squad(valid_squad(), R) == []


def test_rechaza_tamano_incorrecto():
    s = Squad(players=build(n=14))
    assert any(v.code == "SQUAD_SIZE" for v in validate_squad(s, R))


def test_rechaza_composicion_incorrecta():
    s = Squad(players=build(comp=(3, 4, 5, 3)))
    codes = [v.code for v in validate_squad(s, R)]
    assert codes.count("COMPOSITION") == 2      # sobran GKP, faltan DEF


def test_rechaza_mas_de_tres_por_club():
    s = Squad(players=build(clubs=["Arsenal"] * 4 + [f"C{i}" for i in range(11)]))
    v = [x for x in validate_squad(s, R) if x.code == "MAX_PER_CLUB"]
    assert v and "Arsenal" in v[0].detail


def test_rechaza_presupuesto_excedido():
    s = Squad(players=build(price=7.0))          # 15 x 7.0 = 105M
    assert any(v.code == "BUDGET" for v in validate_squad(s, R))


def test_banco_amplia_el_presupuesto():
    s = Squad(players=build(price=6.8), bank=2.0)   # 102M con 2M en banco
    assert not any(v.code == "BUDGET" for v in validate_squad(s, R))


@pytest.mark.parametrize("formation", [(1, 4, 4, 2), (1, 3, 4, 3), (1, 3, 5, 2), (1, 5, 3, 2), (1, 5, 4, 1)])
def test_acepta_formaciones_validas(formation):
    players = build()
    xi, bench = lineup(players, formation)
    s = Squad(players=players, starters=xi, captain=xi[1], vice_captain=xi[2], bench_order=bench)
    assert validate_squad(s, R) == [], formation


@pytest.mark.parametrize("formation,code", [((1, 2, 5, 3), "FORMATION_MIN"), ((1, 5, 5, 0), "FORMATION_MIN")])
def test_rechaza_formaciones_invalidas(formation, code):
    players = build()
    xi, bench = lineup(players, formation)
    s = Squad(players=players, starters=xi, captain=xi[1], vice_captain=xi[2], bench_order=bench)
    assert any(v.code == code for v in validate_squad(s, R))


def test_rechaza_capitan_fuera_del_xi():
    s = valid_squad()
    roto = Squad(players=s.players, starters=s.starters, captain=s.bench_order[0],
                 vice_captain=s.starters[2], bench_order=s.bench_order)
    assert any(v.code == "CAPTAIN_NOT_STARTING" for v in validate_squad(roto, R))


def test_rechaza_capitan_igual_a_vice():
    s = valid_squad()
    roto = Squad(players=s.players, starters=s.starters, captain=s.starters[1],
                 vice_captain=s.starters[1], bench_order=s.bench_order)
    assert any(v.code == "CAPTAIN_IS_VICE" for v in validate_squad(roto, R))


def test_devuelve_todas_las_violaciones_no_la_primera():
    s = Squad(players=build(comp=(3, 4, 5, 3), clubs=["X"] * 15, price=9.0))
    codes = {v.code for v in validate_squad(s, R)}
    assert {"COMPOSITION", "MAX_PER_CLUB", "BUDGET"} <= codes


# --------------------------------------------------- AC-WP002-004

def test_autosub_reemplaza_titular_sin_minutos():
    s = valid_squad()
    minutos = {e: 90 for e in s.starters} | {s.starters[-1]: 0, s.bench_order[1]: 90}
    xi, subs = apply_auto_subs(s, minutos, R)
    assert len(subs) == 1 and subs[0][0] == s.starters[-1]
    assert len(xi) == 11


def test_autosub_no_toca_nada_si_todos_jugaron():
    s = valid_squad()
    xi, subs = apply_auto_subs(s, {e: 90 for e in s.starters}, R)
    assert subs == [] and list(xi) == list(s.starters)


def test_autosub_portero_solo_entra_por_portero():
    s = valid_squad()
    gk_xi = s.starters[0]
    gk_bench = next(p.element for p in s.players
                    if p.position is P.GKP and p.element != gk_xi)
    minutos = {e: 90 for e in s.starters} | {gk_xi: 0, gk_bench: 90}
    xi, subs = apply_auto_subs(s, minutos, R)
    assert (gk_xi, gk_bench) in subs


def test_autosub_respeta_formacion_minima():
    """Con 3 DEF en el XI, un DEF sin minutos no puede salir por un MID."""
    players = build()
    xi, bench = lineup(players, (1, 3, 4, 3))
    s = Squad(players=players, starters=xi, captain=xi[1], vice_captain=xi[2], bench_order=bench)
    defensa = next(e for e in xi if next(p for p in players if p.element == e).position is P.DEF)
    solo_mid = [e for e in bench if next(p for p in players if p.element == e).position is P.MID]
    minutos = {e: 90 for e in xi} | {defensa: 0} | {e: 90 for e in solo_mid}
    nuevo_xi, subs = apply_auto_subs(s, minutos, R)
    assert subs == [], "no debio sustituir: bajaria de 3 defensas"
    assert defensa in nuevo_xi


def test_autosub_no_entra_suplente_que_tampoco_jugo():
    s = valid_squad()
    minutos = {e: 90 for e in s.starters} | {s.starters[-1]: 0} | {e: 0 for e in s.bench_order}
    _, subs = apply_auto_subs(s, minutos, R)
    assert subs == []


def test_vice_asume_si_el_capitan_no_jugo():
    s = valid_squad()
    assert effective_captain(s, {s.captain: 0, s.vice_captain: 90}) == s.vice_captain
    assert effective_captain(s, {s.captain: 12, s.vice_captain: 90}) == s.captain


# --------------------------------------------------- mercado

@pytest.mark.parametrize("n,free,esperado", [(0, 1, 0), (1, 1, 0), (2, 1, 4), (3, 1, 8), (5, 5, 0), (6, 5, 4)])
def test_costo_de_transferencias(n, free, esperado):
    assert transfer_cost(n, free) == esperado


@pytest.mark.parametrize("free,used,esperado", [(1, 0, 2), (1, 1, 1), (5, 0, 5), (5, 2, 4), (3, 3, 1)])
def test_acumulacion_de_transferencias_libres(free, used, esperado):
    assert accumulate_free_transfers(free, used) == esperado


@pytest.mark.parametrize("compra,actual,venta", [
    (5.0, 5.0, 5.0),      # sin cambio
    (5.0, 4.7, 4.7),      # bajada completa
    (5.0, 5.2, 5.1),      # subida 0.2 -> se recupera 0.1
    (5.0, 5.1, 5.0),      # subida 0.1 -> se recupera 0
    (5.0, 5.6, 5.3),      # subida 0.6 -> se recuperan 0.3
    (5.0, 5.5, 5.2),      # subida 0.5 -> 0.2 (redondeo hacia abajo)
])
def test_precio_de_venta(compra, actual, venta):
    assert selling_price(compra, actual) == venta


def test_valor_de_plantilla_usa_precio_de_venta():
    players = (SquadPlayer(1, P.MID, "A", price=6.0, purchase_price=5.0),)
    assert squad_value(players) == 5.5
    assert squad_value(players, use_selling_price=False) == 6.0


# --------------------------------------------------- AC-WP002-005

def test_diff_entre_temporadas_es_solo_bps():
    d = compute("2025-26", "2026-27")
    assert d["scoring"] == [], f"la puntuacion base no debio cambiar: {d['scoring']}"
    assert d["squad"] == [] and d["chips"] == []
    assert d["bps"] == CAMBIOS_2026_27


def test_umbrales_defcon_no_cambiaron():
    a, b = get("2025-26").SCORING, get("2026-27").SCORING
    assert a.defcon_thresholds == b.defcon_thresholds
    assert a.defcon_points == b.defcon_points == 2
