"""El contrato del agente: que puede mover, que no, y que todo quede medido.

La regla que se prueba aqui es la que sostiene el diseno: el agente mueve
ENTRADAS. Si algun dia alguien le da acceso a la salida, estas pruebas fallan.
"""
from __future__ import annotations

import pytest

from mova_fpl.agent import Intervention, apply, describe, merge, validate
from mova_fpl.agent.attribution import measure, settle, summarize
from mova_fpl.engine.runner import Config, decide
from mova_fpl.engine.state import Candidate, State
from mova_fpl.rules import get as get_rules
from mova_fpl.rules.base import Position, Squad, SquadPlayer

RULES = get_rules("2025-26").SQUAD
CATALOGO = get_rules("2025-26").CHIPS


def mercado(n_por_pos=(5, 12, 12, 7)):
    out, e = [], 1
    for pos, n in zip((Position.GKP, Position.DEF, Position.MID, Position.FWD), n_por_pos):
        for k in range(n):
            out.append(Candidate(element=e, position=pos, team=f"C{e % 10}",
                                 price=round(4.0 + 0.1 * k, 1), xp=2.0 + 0.4 * k,
                                 name=f"{pos.value}{e}"))
            e += 1
    return tuple(out)


def estado(cands=None, gw=5, squad=None):
    cands = cands or mercado()
    return State(season="2025-26", gw=gw, candidates=cands, squad=squad,
                 rules=RULES, chips=CATALOGO,
                 horizon_xp={gw: {c.element: c.xp for c in cands}})


# ------------------------------------------------------------------ validacion

def test_una_intervencion_sin_motivo_no_se_puede_auditar():
    st = estado()
    iv = Intervention(gw=5, author="agent", rationale="", xp_multiplier={1: 0.5})
    assert "INTERVENTION_NO_RATIONALE" in [v.code for v in validate(iv, st)]


def test_intervencion_vacia_no_exige_motivo():
    st = estado()
    assert validate(Intervention(gw=5, author="agent"), st) == []


def test_no_se_puede_intervenir_una_jornada_distinta():
    st = estado(gw=5)
    iv = Intervention(gw=7, author="agent", rationale="x")
    assert "INTERVENTION_WRONG_GW" in [v.code for v in validate(iv, st)]


def test_el_multiplicador_esta_acotado():
    """Un agente matiza el modelo; no lo sustituye por su opinion."""
    st = estado()
    iv = Intervention(gw=5, author="agent", rationale="crack", xp_multiplier={1: 9.0})
    assert "MULTIPLIER_OUT_OF_RANGE" in [v.code for v in validate(iv, st)]


def test_no_se_puede_ajustar_a_un_jugador_inexistente():
    st = estado()
    iv = Intervention(gw=5, author="agent", rationale="x", xp_multiplier={99999: 1.2})
    assert "UNKNOWN_PLAYER" in [v.code for v in validate(iv, st)]


def test_proteger_y_vetar_al_mismo_jugador_es_contradictorio():
    st = estado()
    iv = Intervention(gw=5, author="agent", rationale="x",
                      lock_in=frozenset({1}), lock_out=frozenset({1}))
    codigos = [v.code for v in validate(iv, st)]
    assert "LOCK_CONFLICT" in codigos


def test_no_se_puede_proteger_a_quien_no_se_tiene():
    st = estado()
    iv = Intervention(gw=5, author="agent", rationale="x", lock_in=frozenset({3}))
    assert "LOCK_IN_NOT_OWNED" in [v.code for v in validate(iv, st)]


def test_no_se_puede_autorizar_un_chip_ya_gastado():
    from mova_fpl.rules.chips import ChipUse
    cands = mercado()
    st = State(season="2025-26", gw=5, candidates=cands, rules=RULES, chips=CATALOGO,
               chips_used=(ChipUse(gw=2, chip="wildcard"),))
    iv = Intervention(gw=5, author="agent", rationale="x",
                      allow_chips=frozenset({"wildcard"}))
    assert "CHIP_EXHAUSTED" in [v.code for v in validate(iv, st)]


def test_apply_estricto_rechaza_lo_invalido():
    st = estado()
    iv = Intervention(gw=5, author="agent", rationale="x", xp_multiplier={99999: 1.2})
    with pytest.raises(ValueError, match="invalida"):
        apply(st, iv)


# ------------------------------------------------------------------ aplicacion

def test_el_ajuste_de_xp_llega_al_estado_y_al_horizonte():
    st = estado()
    iv = Intervention(gw=5, author="agent:noticias", rationale="duda en rueda de prensa",
                      xp_multiplier={1: 0.0, 2: 1.5})
    nuevo = apply(st, iv)
    por_id = {c.element: c for c in nuevo.candidates}
    original = {c.element: c for c in st.candidates}
    assert por_id[1].xp == 0.0
    assert por_id[2].xp == pytest.approx(original[2].xp * 1.5)
    assert nuevo.horizon_xp[5][1] == 0.0
    assert nuevo.horizon_xp[5][2] == pytest.approx(original[2].xp * 1.5)


def test_aplicar_no_muta_el_estado_original():
    st = estado()
    antes = [c.xp for c in st.candidates]
    apply(st, Intervention(gw=5, author="a", rationale="x", xp_multiplier={1: 0.0}))
    assert [c.xp for c in st.candidates] == antes


def test_el_veto_de_chip_gana_sobre_la_autorizacion_previa():
    st = estado()
    st = type(st)(**{**{f: getattr(st, f) for f in st.__slots__},
                     "chips_allowed": {5: frozenset({"bench_boost"})}})
    iv = Intervention(gw=5, author="julian", rationale="prefiero guardarlo",
                      block_chips=frozenset({"bench_boost"}))
    assert apply(st, iv).chips_allowed == {}


def test_el_agente_puede_poner_un_chip_sobre_la_mesa():
    st = estado()
    iv = Intervention(gw=5, author="agent", rationale="seis dobles confirmadas",
                      allow_chips=frozenset({"bench_boost"}))
    assert apply(st, iv).chips_allowed[5] == frozenset({"bench_boost"})


# ------------------------------------------------------------------ combinar

def test_apilar_intervenciones_de_varias_fuentes():
    a = Intervention(gw=5, author="planner", rationale="calendario",
                     allow_chips=frozenset({"triple_captain"}))
    b = Intervention(gw=5, author="agent:noticias", rationale="lesion",
                     xp_multiplier={1: 0.0})
    m = merge(a, b)
    assert m.allow_chips == frozenset({"triple_captain"})
    assert m.xp_multiplier == {1: 0.0}
    assert "planner" in m.author and "agent:noticias" in m.author
    assert "calendario" in m.rationale and "lesion" in m.rationale


def test_no_se_combinan_intervenciones_de_jornadas_distintas():
    with pytest.raises(ValueError):
        merge(Intervention(gw=5, author="a"), Intervention(gw=6, author="b"))


# ------------------------------------------------------------------ medicion

def test_una_intervencion_sin_efecto_se_reporta_como_tal():
    """Ajustar a un jugador que el optimizador no iba a usar no cambia nada."""
    st = estado()
    cfg = Config(policy="milp", top_k=0)
    peor = min(st.candidates, key=lambda c: c.xp).element
    iv = Intervention(gw=5, author="agent", rationale="da igual",
                      xp_multiplier={peor: 0.9})
    ficha = measure(st, iv, cfg, decide)
    assert ficha.changed is False


def test_una_intervencion_que_cambia_la_decision_queda_registrada():
    st = estado()
    cfg = Config(policy="milp", top_k=0)
    base = decide(5, st, cfg)
    iv = Intervention(gw=5, author="agent:noticias", rationale="lesionado, no juega",
                      xp_multiplier={base.captain: 0.0})
    ficha = measure(st, iv, cfg, decide)
    assert ficha.changed is True
    assert ficha.expected_delta < 0          # quitar al capitan baja el xp esperado
    assert ficha.detail["capitan_sin"] == base.captain
    assert ficha.detail["capitan_con"] != base.captain


def test_el_valor_realizado_solo_existe_despues_de_jugar():
    st = estado()
    cfg = Config(policy="milp", top_k=0)
    iv = Intervention(gw=5, author="agent", rationale="x",
                      xp_multiplier={decide(5, st, cfg).captain: 0.0})
    ficha = measure(st, iv, cfg, decide)
    assert ficha.realized_delta is None
    cerrada = settle(ficha, points_with=60, points_without=52)
    assert cerrada.realized_delta == 8


def test_el_balance_separa_lo_prometido_de_lo_entregado():
    """La calibracion es la metrica que de verdad retrata a un agente."""
    from mova_fpl.agent.attribution import Attribution
    fichas = [
        settle(Attribution(gw=1, author="a", rationale="", expected_delta=10.0, changed=True),
               70, 60),                                    # prometio 10, dio 10
        settle(Attribution(gw=2, author="a", rationale="", expected_delta=10.0, changed=True),
               50, 55),                                    # prometio 10, dio -5
        Attribution(gw=3, author="a", rationale="", expected_delta=0.0, changed=False),
    ]
    r = summarize(fichas)
    assert r["intervenciones"] == 3
    assert r["con_efecto"] == 2
    assert r["valor_realizado"] == 5
    assert r["valor_esperado"] == 20.0
    assert r["calibracion"] == 7.5           # promete 7.5 puntos de mas por intervencion
    assert r["aciertos"] == 1 and r["fallos"] == 1


# ------------------------------------------------------------------ frontera

def test_la_intervencion_no_puede_tocar_la_salida():
    """Ningun campo del contrato permite fijar plantilla, once o capitan.

    Es la regla del diseno, escrita como prueba: si alguien anade un campo tipo
    `force_captain`, esto falla y obliga a discutirlo.
    """
    prohibidos = {"squad", "squad_15", "starters", "captain", "vice_captain",
                  "bench_order", "transfers_in", "transfers_out", "hits", "chip"}
    assert prohibidos & set(Intervention.__slots__) == set()


def test_la_intervencion_es_serializable_ida_y_vuelta():
    """La bitacora guarda el valor tal cual y tiene que poder reaplicarse igual."""
    iv = Intervention(gw=7, author="agent:noticias", rationale="parte medico",
                      xp_multiplier={3: 0.5, 9: 1.2},
                      allow_chips=frozenset({"free_hit"}),
                      lock_out=frozenset({4}), risk_lambda=0.3)
    vuelta = Intervention.from_dict(iv.to_dict())
    assert vuelta == iv


def test_describe_es_legible_para_un_humano():
    iv = Intervention(gw=5, author="agent:noticias", rationale="tres bajas confirmadas",
                      xp_multiplier={1: 0.0, 2: 0.0, 3: 1.2})
    texto = describe(iv)
    assert "agent:noticias" in texto and "tres bajas confirmadas" in texto
    assert "3 jugadores" in texto
