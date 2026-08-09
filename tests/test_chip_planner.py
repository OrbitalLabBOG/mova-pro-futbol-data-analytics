"""El planificador de chips: cuando pone un chip sobre la mesa y cuando lo guarda.

Lo que se prueba no es que acierte —eso lo dice el backtest— sino que su LOGICA
sea la declarada: no desperdicia chips por caducidad, espera si ve algo mejor, y
nunca autoriza algo ilegal.
"""
from __future__ import annotations

import pytest

from mova_fpl.engine.planner import (PlannerConfig, structure_factor, threshold)
from mova_fpl.rules import get as get_rules
from mova_fpl.rules.chips import (ChipUse, ChipWindow, available, expiring,
                                  validate_chip, wasted)

CATALOGO = get_rules("2025-26").CHIPS


# ------------------------------------------------------------ reglas de chips

def test_hay_ocho_chips_en_dos_ventanas():
    """Reforma 2025/26, vigente en 2026/27: dos juegos completos."""
    assert CATALOGO.total() == 8
    assert len(CATALOGO.windows) == 2
    assert CATALOGO.window_for(19).name == "H1"
    assert CATALOGO.window_for(20).name == "H2"


def test_el_inventario_se_refresca_en_la_gw20():
    usados = tuple(ChipUse(gw=g, chip=c) for g, c in
                   ((2, "wildcard"), (5, "bench_boost"), (9, "triple_captain"), (14, "free_hit")))
    assert available(15, usados, CATALOGO) == frozenset()
    assert len(available(20, usados, CATALOGO)) == 4


def test_solo_un_chip_por_jornada():
    usados = (ChipUse(gw=7, chip="wildcard"),)
    assert available(7, usados, CATALOGO) == frozenset()
    assert "bench_boost" in available(8, usados, CATALOGO)


def test_la_ultima_jornada_de_la_ventana_avisa_de_lo_que_caduca():
    usados = (ChipUse(gw=2, chip="wildcard"),)
    assert expiring(18, usados, CATALOGO) == frozenset()
    assert expiring(19, usados, CATALOGO) == frozenset(
        {"free_hit", "bench_boost", "triple_captain"})


def test_los_chips_no_usados_se_contabilizan_como_desperdicio():
    usados = (ChipUse(gw=2, chip="wildcard"),)
    perdidos = wasted(usados, CATALOGO, through_gw=19)
    assert len(perdidos) == 3
    assert ("H1", "wildcard") not in perdidos


def test_validate_chip_rechaza_repetir_dentro_de_la_ventana():
    usados = (ChipUse(gw=3, chip="bench_boost"),)
    assert [v.code for v in validate_chip("bench_boost", 10, usados, CATALOGO)] == ["CHIP_EXHAUSTED"]
    assert validate_chip("bench_boost", 25, usados, CATALOGO) == []


# ------------------------------------------------------------ senal de calendario

def test_la_doble_jornada_sube_el_factor_del_bench_boost():
    sched = {("A", 1): 1, ("B", 1): 1, ("A", 3): 2, ("B", 3): 2}
    assert structure_factor("bench_boost", 1, sched) == 1.0
    assert structure_factor("bench_boost", 3, sched) == 2.0


def test_la_jornada_en_blanco_sube_el_factor_del_free_hit():
    sched = {("A", 1): 1, ("B", 1): 1, ("A", 5): 0, ("B", 5): 1}
    assert structure_factor("free_hit", 1, sched) == 1.0
    assert structure_factor("free_hit", 5, sched) == 2.0


def test_el_wildcard_no_depende_del_calendario():
    sched = {("A", 3): 2, ("B", 3): 2}
    assert structure_factor("wildcard", 3, sched) == 1.0


# ------------------------------------------------------------------- umbral

def test_en_la_ultima_jornada_el_umbral_es_cero():
    """Un chip caducado es valor quemado: cualquier valor positivo lo justifica."""
    u, motivo = threshold("bench_boost", 19, restantes=1, valor_ahora=1.0,
                          schedule={}, config=PlannerConfig())
    assert u == 0.0
    assert "pierde" in motivo


def test_si_viene_una_jornada_mejor_el_umbral_sube():
    sched = {("A", g): (2 if g == 4 else 1) for g in range(1, 10)}
    sched.update({("B", g): (2 if g == 4 else 1) for g in range(1, 10)})
    u, motivo = threshold("bench_boost", 1, restantes=18, valor_ahora=10.0,
                          schedule=sched, config=PlannerConfig())
    assert u > 10.0, "con una doble a la vista no deberia jugarse hoy"
    assert "mejor" in motivo


def test_el_umbral_se_relaja_al_acercarse_la_caducidad():
    cfg = PlannerConfig()
    lejos, _ = threshold("wildcard", 5, restantes=15, valor_ahora=5.0, schedule={}, config=cfg)
    cerca, _ = threshold("wildcard", 17, restantes=3, valor_ahora=5.0, schedule={}, config=cfg)
    assert cerca < lejos
    assert lejos == pytest.approx(cfg.pisos["wildcard"])


def test_el_lookahead_acota_lo_que_el_planificador_puede_ver():
    """Honestidad de calendario: una doble a 10 jornadas no debe influir hoy."""
    sched = {("A", g): (2 if g == 12 else 1) for g in range(1, 20)}
    corto = PlannerConfig(structure_lookahead=6)
    largo = PlannerConfig(structure_lookahead=15)
    u_corto, _ = threshold("bench_boost", 1, 18, 10.0, sched, corto)
    u_largo, _ = threshold("bench_boost", 1, 18, 10.0, sched, largo)
    assert u_corto < u_largo, "el planificador miope no puede reaccionar a la GW12"
