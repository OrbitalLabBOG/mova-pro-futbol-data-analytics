"""WP-003: circuito completo, identidad de decide(), baselines y reanudacion."""
from __future__ import annotations

from pathlib import Path

import pytest

from mova_fpl.data.store import Store
from mova_fpl.engine.runner import Config, decide
from mova_fpl.engine.simulator import replay
from mova_fpl.engine.state import Candidate, State
from mova_fpl.rules import get
from mova_fpl.rules.base import Position
from mova_fpl.rules.squad import validate_squad
from mova_fpl.trace import TraceWriter
from mova_fpl.trace.query import decisions, summary, vs_baseline

RULES = get("2025-26").SQUAD


def sintetico(n=60, seed=0) -> tuple[Candidate, ...]:
    """Mercado determinista: sin aleatoriedad, para comparar byte a byte."""
    comp = [(Position.GKP, 12), (Position.DEF, 18), (Position.MID, 18), (Position.FWD, 12)]
    out, e = [], 1
    for pos, k in comp:
        for i in range(k):
            out.append(Candidate(element=e, position=pos, team=f"C{e % 12}",
                                 price=4.0 + (i % 6) * 0.5, xp=1.0 + (i * 0.37) % 5, name=f"P{e}"))
            e += 1
    return tuple(out)


@pytest.fixture
def state_gw1() -> State:
    return State(season="2025-26", gw=1, candidates=sintetico(), squad=None,
                 free_transfers=1, bank=0.0, rules=RULES)


# ------------------------------------------------ AC-WP003-005: identidad

def test_misma_entrada_misma_decision(state_gw1):
    a = decide(1, state_gw1, Config())
    b = decide(1, state_gw1, Config())
    assert a.fingerprint() == b.fingerprint()
    assert a == b


def test_decide_rechaza_gw_inconsistente(state_gw1):
    with pytest.raises(ValueError, match="no coincide"):
        decide(7, state_gw1, Config())


def test_decide_rechaza_politica_desconocida(state_gw1):
    with pytest.raises(ValueError, match="politica desconocida"):
        decide(1, state_gw1, Config(policy="inexistente"))


def test_la_decision_respeta_las_reglas(state_gw1):
    from mova_fpl.rules.base import Squad, SquadPlayer
    d = decide(1, state_gw1, Config())
    by_id = state_gw1.by_id()
    squad = Squad(
        players=tuple(SquadPlayer(e, by_id[e].position, by_id[e].team, by_id[e].price)
                      for e in d.squad_15),
        starters=d.starters, captain=d.captain, vice_captain=d.vice_captain,
        bench_order=d.bench_order)
    assert validate_squad(squad, RULES) == []


def test_cold_start_no_lee_datos_de_la_temporada(state_gw1):
    assert state_gw1.is_cold_start
    d = decide(1, state_gw1, Config())
    assert len(d.squad_15) == 15 and d.transfers_in == ()


# ------------------------------------------------ circuito completo

@pytest.fixture(scope="module")
def corrida(tmp_path_factory):
    trace = TraceWriter(tmp_path_factory.mktemp("t") / "trace.db")
    rep = replay("2025-26", "anonymized", Config(seed=42), store=Store(), trace=trace,
                 run_id="test-run", max_gw=6, verbose=False)
    return rep, trace


@pytest.mark.integration_data
def test_replay_recorre_las_jornadas(corrida):
    rep, _ = corrida
    assert [g["gw"] for g in rep.gameweeks] == [1, 2, 3, 4, 5, 6]
    assert rep.total > 0


@pytest.mark.integration_data
def test_gw1_es_cold_start_sin_datos(corrida):
    rep, _ = corrida
    assert rep.gameweeks[0]["train_rows"] == 0, "GW1 no puede tener filas de entrenamiento"
    assert all(g["train_rows"] > 0 for g in rep.gameweeks[1:])


@pytest.mark.integration_data
def test_las_filas_de_entrenamiento_crecen(corrida):
    rep, _ = corrida
    filas = [g["train_rows"] for g in rep.gameweeks]
    assert filas == sorted(filas)


# ------------------------------------------------ AC-WP003-004: baselines

@pytest.mark.integration_data
def test_el_reporte_trae_los_tres_baselines(corrida):
    rep, _ = corrida
    assert set(rep.baselines) == {"template", "random", "ceiling"}
    assert all(v > 0 for v in rep.baselines.values())


@pytest.mark.integration_data
def test_el_techo_acota_por_arriba(corrida):
    rep, _ = corrida
    assert rep.baselines["ceiling"] >= rep.total
    assert rep.baselines["ceiling"] >= rep.baselines["template"]


@pytest.mark.integration_data
def test_template_nunca_es_cero(corrida):
    """Regresion: el error de punto flotante lo dejaba en 0 en 14 de 38 jornadas."""
    rep, _ = corrida
    assert all(g["template"] > 0 for g in rep.gameweeks)


# ------------------------------------------------ AC-WP003-006/007: traza

@pytest.mark.integration_data
def test_la_traza_registra_cada_jornada(corrida):
    rep, trace = corrida
    d = decisions("test-run", trace.db_path)
    assert len(d) == 6
    assert d["actual_points"].notna().all()
    assert (d["state"] == "reconciled").all()


@pytest.mark.integration_data
def test_la_traza_responde_quien_gano(corrida):
    """AC-WP003-007: la pregunta que justifica tener traza."""
    _, trace = corrida
    cmp = vs_baseline("test-run", "template", trace.db_path)
    assert len(cmp) == 6
    assert set(cmp["gana"]) <= {"motor", "baseline", "empate"}
    assert (cmp["motor"] - cmp["baseline"] == cmp["delta"]).all()


@pytest.mark.integration_data
def test_resumen_de_corrida(corrida):
    rep, trace = corrida
    s = summary("test-run", trace.db_path)
    assert s["gameweeks"] == 6 and s["motor"] == rep.total
    assert set(s["baselines"]) == {"template", "random", "ceiling"}


@pytest.mark.integration_data
def test_reproducibilidad_con_la_misma_semilla(tmp_path):
    """AC-WP003-006."""
    huellas = []
    for i in range(2):
        tr = TraceWriter(tmp_path / f"t{i}.db")
        replay("2025-26", "anonymized", Config(seed=7), trace=tr, run_id=f"r{i}",
               max_gw=4, verbose=False)
        huellas.append(tuple(decisions(f"r{i}", tr.db_path)["fingerprint"]))
    assert huellas[0] == huellas[1]


@pytest.mark.integration_data
def test_reanudacion_no_recomputa(tmp_path):
    """AC-WP003-008."""
    tr = TraceWriter(tmp_path / "t.db")
    replay("2025-26", "anonymized", Config(seed=1), trace=tr, run_id="rr", max_gw=3, verbose=False)
    antes = decisions("rr", tr.db_path)
    parcial = replay("2025-26", "anonymized", Config(seed=1), trace=tr, run_id="rr",
                     resume=True, max_gw=5, verbose=False)
    assert [g["gw"] for g in parcial.gameweeks] == [4, 5], "no debio rehacer 1..3"
    despues = decisions("rr", tr.db_path)
    assert len(despues) == 5
    assert list(antes["fingerprint"]) == list(despues["fingerprint"][:3])


@pytest.mark.integration_data
def test_modo_anonimo_oculta_identidades():
    from mova_fpl.engine.simulator import _alias_equipos, _anonymize
    store = Store()
    alias = _alias_equipos(store, "2025-26")
    r = store.roster("2025-26", 5)
    a = _anonymize(r, alias)
    assert not set(a["team"]) & set(r["team"])
    assert a["team"].str.startswith("CLUB_").all()
    assert set(a["element"]) == set(r["element"]), "los ids deben ser estables"


@pytest.mark.integration_data
def test_el_alias_de_club_es_estable_en_toda_la_temporada():
    """Un mapa por jornada corria los indices en jornadas incompletas y `CLUB_03`
    dejaba de ser el mismo equipo. La cuota de tres por club se evaluaba entonces
    sobre identidades distintas segun la jornada."""
    from mova_fpl.engine.simulator import _alias_equipos, _anonymize
    store = Store()
    alias = _alias_equipos(store, "2025-26")
    pares = {}
    for gw in (1, 5, 20, 38):
        r = store.roster("2025-26", gw)
        if r.empty:
            continue
        a = _anonymize(r, alias)
        for real, falso in zip(r["team"], a["team"]):
            assert pares.setdefault(real, falso) == falso, f"{real} cambio de alias en GW{gw}"
