"""WP-005: el xP es la suma de sus componentes, y cada componente se sostiene solo.

La afirmacion central de ADR-003 es que descomponer sirve. Estas pruebas verifican
que la descomposicion es COHERENTE (la suma cuadra, las reglas se respetan por
rama) — que sea MEJOR se mide en el harness, no aqui.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mova_fpl.models.cleansheet import CleanSheetModel, esperanza_mitades, p_cero
from mova_fpl.models.points import COMPONENTES, PointsModel
from mova_fpl.rules import get as get_rules
from mova_fpl.rules.base import Position

REGLAS = get_rules("2025-26")
SCORING = REGLAS.SCORING
UMBRALES = SCORING.defcon_thresholds


def catalogo(n=8, posiciones=("GKP", "DEF", "MID", "FWD")) -> pd.DataFrame:
    filas = []
    for i in range(n):
        p = posiciones[i % len(posiciones)]
        filas.append({"element": i + 1, "player_key": f"jugador {i+1}", "name": f"J{i+1}",
                      "position": p, "team": f"C{i % 4}", "value": 50 + i,
                      "opponent_team": (i % 4) + 1, "was_home": i % 2,
                      "fixture": 100 + i, "season": "2025-26", "gw": 10,
                      "kickoff_time": "2025-11-01T15:00:00Z"})
    return pd.DataFrame(filas)


def historia(cat: pd.DataFrame, jornadas=8) -> pd.DataFrame:
    filas = []
    rng = np.random.default_rng(7)
    for gw in range(1, jornadas + 1):
        for _, r in cat.iterrows():
            filas.append({**r.to_dict(), "gw": gw, "fixture": 1000 + gw * 10 + r["element"],
                          "minutes": int(rng.integers(0, 95)),
                          "total_points": int(rng.integers(0, 9)),
                          "goals_scored": int(rng.integers(0, 2)),
                          "assists": int(rng.integers(0, 2)),
                          "expected_goals": float(rng.random() * 0.5),
                          "expected_assists": float(rng.random() * 0.3),
                          "clean_sheets": int(rng.integers(0, 2)),
                          "goals_conceded": int(rng.integers(0, 3)),
                          "own_goals": 0, "penalties_saved": 0, "penalties_missed": 0,
                          "yellow_cards": int(rng.integers(0, 2)), "red_cards": 0,
                          "saves": int(rng.integers(0, 5)) if r["position"] == "GKP" else 0,
                          "bonus": int(rng.integers(0, 4)), "bps": int(rng.integers(0, 40)),
                          "starts": 1, "defensive_contribution": int(rng.integers(0, 16)),
                          "clearances_blocks_interceptions": int(rng.integers(0, 10)),
                          "recoveries": int(rng.integers(0, 10)),
                          "tackles": int(rng.integers(0, 5)),
                          "team_h_score": int(rng.integers(0, 4)),
                          "team_a_score": int(rng.integers(0, 4))})
    return pd.DataFrame(filas)


def proba(n, p0=0.1, p1=0.2, p60=0.7) -> np.ndarray:
    return np.tile(np.array([p0, p1, p60], dtype=float), (n, 1))


@pytest.fixture(scope="module")
def modelo():
    cat = catalogo()
    return PointsModel().fit(historia(cat)), cat


# ---------------------------------------------------------------- AC-WP005-001

def test_la_suma_de_componentes_es_el_total(modelo):
    pm, cat = modelo
    out = pm.project(historia(cat), cat, proba(len(cat)), SCORING, UMBRALES)
    suma = out[list(COMPONENTES)].sum(axis=1)
    assert np.allclose(suma, out["xp"], atol=1e-9)


def test_la_suma_cuadra_tambien_con_datos_reales():
    from mova_fpl.data.store import Store
    from mova_fpl.engine.projection import _proba_minutos
    from mova_fpl.models.registry import load

    store = Store()
    pm = PointsModel().fit(store.multi_season_as_of("2025-26", 1))
    hist, roster = store.as_of("2025-26", 20), store.roster("2025-26", 20)
    p = _proba_minutos(hist, roster, load("minutes", "1.0.0"))
    out = pm.project(hist, roster, p, SCORING, UMBRALES)
    assert len(out) == len(roster)
    assert np.allclose(out[list(COMPONENTES)].sum(axis=1), out["xp"], atol=1e-6)


# ---------------------------------------------------------------- AC-WP005-002

def test_project_devuelve_el_desglose_no_solo_el_total(modelo):
    pm, cat = modelo
    out = pm.project(historia(cat), cat, proba(len(cat)), SCORING, UMBRALES)
    for c in COMPONENTES:
        assert c in out.columns, f"falta el componente {c}"
    for c in ("p_juega", "p_60", "p_porteria_cero", "p_defcon", "lambda_encajados"):
        assert c in out.columns, f"falta el diagnostico {c}"


# ---------------------------------------------------------------- AC-WP005-007

def test_cada_fila_reporta_incertidumbre(modelo):
    pm, cat = modelo
    out = pm.project(historia(cat), cat, proba(len(cat)), SCORING, UMBRALES)
    assert (out["xp_sd"] >= 0).all()
    assert (out["xp_sd"] > 0).all(), "un jugador que puede jugar no puede tener sd = 0"


def test_la_incertidumbre_crece_cuando_no_se_sabe_si_juega(modelo):
    """Un rotativo 50/50 es mas incierto que un fijo, aunque su xP sea menor.

    Es el termino de mezcla de la varianza. Sin el, el optimizador no distingue
    entre 3 puntos seguros y 3 puntos que salen de una moneda.
    """
    pm, cat = modelo
    h = historia(cat)
    fijo = pm.project(h, cat, proba(len(cat), 0.02, 0.03, 0.95), SCORING, UMBRALES)
    dudoso = pm.project(h, cat, proba(len(cat), 0.50, 0.05, 0.45), SCORING, UMBRALES)
    # se compara la sd RELATIVA al xP: el dudoso vale menos, pero es mas volatil
    assert (dudoso["xp_sd"] / dudoso["xp"]).mean() > (fijo["xp_sd"] / fijo["xp"]).mean()


# --------------------------------------------------- reglas dentro de cada rama

def test_quien_no_juega_no_puntua(modelo):
    pm, cat = modelo
    out = pm.project(historia(cat), cat, proba(len(cat), 1.0, 0.0, 0.0), SCORING, UMBRALES)
    assert np.allclose(out["xp"], 0.0)
    assert np.allclose(out["xp_sd"], 0.0)


def test_la_porteria_a_cero_solo_puntua_en_la_rama_de_60(modelo):
    """FPL exige 60 minutos para la porteria a cero. Con P(60+) = 0 no hay puntos."""
    pm, cat = modelo
    h = historia(cat)
    solo_parcial = pm.project(h, cat, proba(len(cat), 0.0, 1.0, 0.0), SCORING, UMBRALES)
    assert np.allclose(solo_parcial["pts_cs"], 0.0)
    con_60 = pm.project(h, cat, proba(len(cat), 0.0, 0.0, 1.0), SCORING, UMBRALES)
    assert (con_60["pts_cs"] > 0).any()


def test_los_puntos_de_aparicion_son_uno_o_dos_nunca_intermedios(modelo):
    pm, cat = modelo
    h = historia(cat)
    parcial = pm.project(h, cat, proba(len(cat), 0.0, 1.0, 0.0), SCORING, UMBRALES)
    completo = pm.project(h, cat, proba(len(cat), 0.0, 0.0, 1.0), SCORING, UMBRALES)
    assert np.allclose(parcial["pts_aparicion"], SCORING.appearance_short)
    assert np.allclose(completo["pts_aparicion"], SCORING.appearance_long)


def test_el_portero_no_recibe_puntos_de_contribucion_defensiva(modelo):
    pm, cat = modelo
    out = pm.project(historia(cat), cat, proba(len(cat)), SCORING, UMBRALES)
    gk = out[cat["position"].to_numpy() == "GKP"]
    assert np.allclose(gk["pts_defcon"], 0.0)
    assert np.allclose(gk["p_defcon"], 0.0)


def test_solo_portero_y_defensa_pagan_los_goles_encajados(modelo):
    pm, cat = modelo
    out = pm.project(historia(cat), cat, proba(len(cat)), SCORING, UMBRALES)
    fuera = out[np.isin(cat["position"].to_numpy(), ["MID", "FWD"])]
    assert np.allclose(fuera["pts_encajados"], 0.0)
    atras = out[np.isin(cat["position"].to_numpy(), ["GKP", "DEF"])]
    assert (atras["pts_encajados"] < 0).all()


# ------------------------------------------------------- distribuciones exactas

@pytest.mark.parametrize("lam,esperado", [(0.5, 0.6065), (1.0, 0.3679), (2.0, 0.1353)])
def test_p_porteria_cero_es_la_poisson_en_cero(lam, esperado):
    assert p_cero(np.array([lam]))[0] == pytest.approx(esperado, abs=1e-4)


def test_la_penalizacion_por_goles_no_es_la_mitad_de_la_media():
    """E[floor(X/2)] != lambda/2. Usar la mitad castigaba casi el doble."""
    lam = np.array([0.5, 1.0, 1.5, 2.0])
    exacto = esperanza_mitades(lam)
    assert (exacto < lam / 2).all()
    assert exacto[1] == pytest.approx(0.28383, abs=1e-4)   # suma directa de la Poisson(1)


def test_la_penalizacion_crece_con_los_goles_esperados():
    v = esperanza_mitades(np.array([0.2, 1.0, 2.0, 3.0]))
    assert (np.diff(v) > 0).all()


def test_el_modelo_de_cs_usa_la_tabla_de_la_temporada():
    """Los puntos no estan escritos en el modelo: salen de las reglas."""
    cs = CleanSheetModel()
    out = cs.project(np.array([0.8, 0.8]), ["DEF", "MID"], SCORING)
    assert out["puntos_cs"][0] == pytest.approx(
        out["p_porteria_cero"][0] * SCORING.clean_sheet_points[Position.DEF])
    assert out["puntos_cs"][1] == pytest.approx(
        out["p_porteria_cero"][1] * SCORING.clean_sheet_points[Position.MID])
