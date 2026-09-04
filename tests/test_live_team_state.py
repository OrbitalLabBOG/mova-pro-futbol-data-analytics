"""Lectura del estado real del equipo desde los endpoints publicos.

No se puede probar contra la temporada en curso hasta que se juegue la GW1, asi
que se prueba contra cargas sinteticas con la forma REAL de la API —verificada
contra `/entry/{id}/history/`: claves `chips`, `current`, `past`—.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

from mova_fpl.data import live
from mova_fpl.rules import get as get_rules
from mova_fpl.rules.base import Position
from mova_fpl.rules.chips import ChipUse

RULES = get_rules("2025-26").SQUAD


def historia(chips=(), transferencias=None, hasta=10):
    """Replica de `/api/entry/{id}/history/`."""
    transferencias = transferencias or {}
    return {
        "chips": [{"name": n, "event": g} for n, g in chips],
        "current": [{"event": g, "points": 50, "bank": 5,
                     "event_transfers": transferencias.get(g, 0),
                     "event_transfers_cost": 0} for g in range(1, hasta + 1)],
        "past": [],
    }


def bootstrap(n=20):
    """Replica minima de `bootstrap-static`: clubes y jugadores."""
    equipos = [{"id": i, "name": f"Club{i}"} for i in range(1, 6)]
    elementos = []
    for e in range(1, n + 1):
        elementos.append({"id": e, "element_type": 1 + (e % 4), "team": 1 + (e % 5),
                          "now_cost": 45 + e, "first_name": "N", "second_name": f"{e}",
                          "web_name": f"J{e}", "status": "a"})
    return {"teams": equipos, "elements": elementos, "events": []}


def roster_de(boot, elementos):
    filas = []
    clubes = {int(t["id"]): t["name"] for t in boot["teams"]}
    for e in boot["elements"]:
        if int(e["id"]) not in elementos:
            continue
        filas.append({"element": int(e["id"]),
                      "position": live.POSICIONES[int(e["element_type"])],
                      "team": clubes[int(e["team"])], "value": int(e["now_cost"]),
                      "name": e["web_name"]})
    return pd.DataFrame(filas)


# --------------------------------------------------------------------- chips

def test_los_chips_de_la_api_se_traducen_al_motor():
    h = historia(chips=[("wildcard", 4), ("3xc", 9), ("bboost", 12), ("freehit", 15)])
    assert live.chips_used(h) == (
        ChipUse(gw=4, chip="wildcard"), ChipUse(gw=9, chip="triple_captain"),
        ChipUse(gw=12, chip="bench_boost"), ChipUse(gw=15, chip="free_hit"))


def test_un_chip_que_ya_no_existe_no_rompe_la_lectura():
    """El `assistant manager` de 2024/25 desaparecio; tropezarse con el no puede
    tumbar una decision de jornada."""
    h = historia(chips=[("manager", 2), ("wildcard", 4)])
    assert live.chips_used(h) == (ChipUse(gw=4, chip="wildcard"),)


def test_sin_chips_gastados_la_lista_va_vacia():
    assert live.chips_used(historia()) == ()


# ------------------------------------------------------- transferencias libres

def test_las_libres_se_reconstruyen_jornada_a_jornada():
    """La API publica no expone el saldo; se deriva de las transferencias hechas."""
    h = historia(transferencias={2: 0, 3: 0, 4: 0}, hasta=4)
    # sin gastar nada desde la GW1: 1 -> 2 -> 3 -> 4 al abrir la GW5
    assert live.free_transfers(h, 5, RULES, ()) == 4


def test_las_libres_tienen_tope():
    h = historia(transferencias={}, hasta=20)
    assert live.free_transfers(h, 21, RULES, ()) == RULES["max_free_transfers"]


def test_gastar_transferencias_baja_el_saldo():
    h = historia(transferencias={2: 0, 3: 2, 4: 0}, hasta=4)
    # gw2: 1 libre, no usa -> 2 | gw3: usa 2 de 2 -> 1 | gw4: no usa -> 2
    assert live.free_transfers(h, 5, RULES, ()) == 2


def test_el_wildcard_no_consume_libres():
    """Regla oficial: con wildcard las acumuladas se conservan."""
    con_wc = historia(chips=[("wildcard", 3)], transferencias={2: 0, 3: 11, 4: 0}, hasta=4)
    usados = live.chips_used(con_wc)
    assert live.free_transfers(con_wc, 5, RULES, usados) == 4

    sin_wc = historia(transferencias={2: 0, 3: 11, 4: 0}, hasta=4)
    assert live.free_transfers(sin_wc, 5, RULES, ()) == 2


def test_el_free_hit_tampoco_consume_libres():
    h = historia(chips=[("freehit", 3)], transferencias={2: 0, 3: 11, 4: 0}, hasta=4)
    assert live.free_transfers(h, 5, RULES, live.chips_used(h)) == 4


# ------------------------------------------------------------------ plantilla

def test_la_plantilla_se_lee_de_los_quince_de_la_ultima_jornada():
    boot = bootstrap()
    elementos = list(range(1, 16))
    picks = {"picks": [{"element": e, "position": i + 1, "multiplier": 1}
                       for i, e in enumerate(elementos)],
             "entry_history": {"bank": 23, "value": 1005}}
    squad, en_blanco = live.squad_from_picks(picks, roster_de(boot, set(elementos)), boot)
    assert len(squad.players) == 15
    assert squad.bank == pytest.approx(2.3)
    assert en_blanco == []


def test_un_jugador_en_jornada_en_blanco_no_desaparece_de_la_plantilla():
    """Sin fila en el roster de esta gw, pero sigue siendo tuyo: el bootstrap lo tiene.

    Descartarlo dejaria catorce jugadores y el optimizador reconstruiria como si
    nunca hubiera existido.
    """
    boot = bootstrap()
    elementos = list(range(1, 16))
    picks = {"picks": [{"element": e, "position": i + 1} for i, e in enumerate(elementos)],
             "entry_history": {"bank": 0}}
    # el roster de la jornada no incluye a tres de ellos
    parcial = roster_de(boot, set(elementos) - {3, 7, 11})
    squad, en_blanco = live.squad_from_picks(picks, parcial, boot)
    assert len(squad.players) == 15
    assert sorted(en_blanco) == [3, 7, 11]
    assert {p.element for p in squad.players} == set(elementos)


def test_un_elemento_inexistente_falla_ruidosamente():
    boot = bootstrap()
    picks = {"picks": [{"element": 99999}], "entry_history": {"bank": 0}}
    with pytest.raises(ValueError, match="no esta en el bootstrap"):
        live.squad_from_picks(picks, roster_de(boot, set()), boot)


# --------------------------------------------------------------- estado entero

def test_team_state_junta_todo(monkeypatch):
    boot = bootstrap()
    elementos = list(range(1, 16))
    h = historia(chips=[("wildcard", 2)], transferencias={2: 0, 3: 1}, hasta=3)
    picks = {"picks": [{"element": e, "position": i + 1} for i, e in enumerate(elementos)],
             "entry_history": {"bank": 15}}

    monkeypatch.setattr(live, "fetch_team_history", lambda i: json.dumps(h).encode())
    monkeypatch.setattr(live, "fetch_team_picks", lambda i, g: json.dumps(picks).encode())

    st = live.team_state(123, 4, roster_de(boot, set(elementos)), RULES, boot)
    assert st["ultima_gw"] == 3
    assert len(st["squad"].players) == 15
    assert st["bank"] == pytest.approx(1.5)
    assert st["chips_used"] == (ChipUse(gw=2, chip="wildcard"),)
    assert st["free_transfers"] >= 1


def test_team_state_detecta_una_plantilla_incompleta(monkeypatch):
    """Si la API devuelve algo raro, se para. Decidir con catorce seria peor."""
    boot = bootstrap()
    h = historia(hasta=3)
    picks = {"picks": [{"element": e} for e in range(1, 15)],   # solo 14
             "entry_history": {"bank": 0}}
    monkeypatch.setattr(live, "fetch_team_history", lambda i: json.dumps(h).encode())
    monkeypatch.setattr(live, "fetch_team_picks", lambda i, g: json.dumps(picks).encode())
    with pytest.raises(ValueError, match="14 jugadores"):
        live.team_state(123, 4, roster_de(boot, set(range(1, 15))), RULES, boot)


def test_fixture_schedule_conserva_ambos_lados_y_contexto_futuro():
    boot = bootstrap()
    fx = [
        {"id": 101, "event": 4, "team_h": 1, "team_a": 2,
         "kickoff_time": "2026-09-10T19:00:00Z"},
        {"id": 102, "event": 5, "team_h": 3, "team_a": 1,
         "kickoff_time": "2026-09-17T19:00:00Z"},
        {"id": 99, "event": 3, "team_h": 1, "team_a": 4},
    ]

    schedule = live.fixture_schedule(fx, boot, 4, 5)

    assert len(schedule) == 4
    assert schedule.groupby("fixture").size().to_dict() == {101: 2, 102: 2}
    club1 = schedule[schedule["team"] == "Club1"].sort_values("gw")
    assert club1[["gw", "opponent_team", "was_home"]].to_dict("records") == [
        {"gw": 4, "opponent_team": 2, "was_home": 1},
        {"gw": 5, "opponent_team": 3, "was_home": 0},
    ]


def test_closed_history_incorpora_solo_eventos_asentados():
    boot = bootstrap(n=1)
    boot["events"] = [
        {"id": 1, "finished": True, "data_checked": True},
        {"id": 2, "finished": False, "data_checked": False},
    ]
    fx = [{
        "id": 11, "event": 1, "team_h": 2, "team_a": 1,
        "team_h_score": 0, "team_a_score": 2,
        "kickoff_time": "2026-08-21T17:30:00Z",
    }]
    payloads = {1: {"elements": [{
        "id": 1,
        "stats": {"minutes": 90, "starts": 1, "total_points": 6},
        "explain": [{"fixture": 11, "stats": []}],
    }]}}

    history, quality = live.closed_history(boot, fx, payloads, "2026-27", 2)

    assert history[["season", "gw", "element", "minutes"]].to_dict("records") == [{
        "season": "2026-27", "gw": 1, "element": 1, "minutes": 90,
    }]
    assert history.iloc[0]["was_home"] == 1
    assert quality["gws"] == [1]


def test_closed_history_no_inventa_club_historico_despues_de_transferencia():
    boot = {
        "events": [{"id": 1, "finished": True, "data_checked": True}],
        "teams": [
            {"id": 1, "name": "Actual"}, {"id": 2, "name": "Old A"},
            {"id": 3, "name": "Old B"}, {"id": 4, "name": "Other"},
        ],
        "elements": [
            {"id": 1, "first_name": "Moved", "second_name": "Player",
             "web_name": "Moved", "team": 1, "element_type": 3, "now_cost": 55},
            {"id": 2, "first_name": "Stable", "second_name": "Player",
             "web_name": "Stable", "team": 2, "element_type": 3, "now_cost": 55},
        ],
    }
    fixtures = [
        {"id": 11, "event": 1, "team_h": 1, "team_a": 4,
         "team_h_score": 0, "team_a_score": 0},
        {"id": 12, "event": 1, "team_h": 2, "team_a": 3,
         "team_h_score": 1, "team_a_score": 0},
    ]
    payloads = {1: {"elements": [
        {"id": 1, "stats": {"minutes": 90},
         "explain": [{"fixture": 12, "stats": []}]},
        {"id": 2, "stats": {"minutes": 90},
         "explain": [{"fixture": 12, "stats": []}]},
    ]}}

    history, quality = live.closed_history(
        boot, fixtures, payloads, "2026-27", 2,
    )

    assert history["element"].tolist() == [2]
    assert quality["skipped_historical_team_mismatch"] == 1

    summaries = {1: {"history": [{
        "round": 1, "fixture": 12, "was_home": False,
    }]}}
    repaired, repaired_quality = live.closed_history(
        boot, fixtures, payloads, "2026-27", 2,
        element_summaries=summaries,
    )

    moved = repaired.set_index("element").loc[1]
    assert moved["team"] == "Old B"
    assert moved["opponent_team"] == 2
    assert moved["was_home"] == 0
    assert repaired_quality["repaired_historical_team_mismatch"] == 1
    assert repaired_quality["skipped_historical_team_mismatch"] == 0


def test_un_equipo_sin_jornadas_jugadas_es_arranque_en_frio(monkeypatch):
    monkeypatch.setattr(live, "fetch_team_history",
                        lambda i: json.dumps({"chips": [], "current": [], "past": []}).encode())
    st = live.team_state(123, 1, pd.DataFrame(), RULES, bootstrap())
    assert st["squad"] is None
    assert st["chips_used"] == ()
