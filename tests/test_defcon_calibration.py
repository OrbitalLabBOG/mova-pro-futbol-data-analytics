"""WP-005: la contribucion defensiva. Es donde el proyecto busca su ventaja.

La regla entro en 2025/26 y el mercado todavia la esta incorporando al precio.
Si el componente esta bien calibrado, el optimizador ve dos puntos por jornada
que el precio no refleja. Si esta mal, los ve donde no estan.

Se evalua por CALIBRACION y no por acierto: al optimizador no le sirve saber que
un central "suele" pasar el umbral, le sirve que cuando el modelo dice 0,4, la
frecuencia real sea 0,4.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mova_fpl.models.defcon import (
    DISPERSION_MAX, DISPERSION_MIN, DISPERSION_POR_DEFECTO, DefConModel, evaluate,
)
from mova_fpl.rules import get as get_rules
from mova_fpl.rules.base import Position

SCORING = get_rules("2025-26").SCORING
UMBRALES = SCORING.defcon_thresholds


def muestra(n=1500, semilla=3) -> pd.DataFrame:
    """Conteos sobredispersos, como los reales: la varianza supera a la media."""
    rng = np.random.default_rng(semilla)
    filas = []
    for i in range(n):
        pos = ("DEF", "MID", "FWD")[i % 3]
        tasa = {"DEF": 8.0, "MID": 9.0, "FWD": 3.0}[pos]
        minutos = int(rng.integers(20, 95))
        mu = tasa * minutos / 90.0
        # gamma-Poisson = binomial negativa: la sobredispersion es explicita
        lam = rng.gamma(shape=8.0, scale=mu / 8.0) if mu > 0 else 0.0
        filas.append({"player_key": f"j{i % 120}", "season": "2025-26", "gw": 1 + i % 20,
                      "position": pos, "minutes": minutos,
                      "defensive_contribution": int(rng.poisson(lam))})
    return pd.DataFrame(filas)


# ----------------------------------------------------------- umbrales y reglas

def test_el_portero_nunca_recibe_puntos_defensivos():
    """GKP no es elegible. No es que sea improbable: es que la regla no aplica."""
    m = DefConModel()
    p = m.p_umbral(np.array([30.0]), np.array([1.0]), ["GKP"], UMBRALES)
    assert p[0] == 0.0


def test_los_umbrales_son_los_de_la_temporada():
    assert UMBRALES[Position.DEF] == 10
    assert UMBRALES[Position.MID] == UMBRALES[Position.FWD] == 12
    assert Position.GKP not in UMBRALES


def test_la_probabilidad_crece_con_la_tasa():
    m = DefConModel()
    p = m.p_umbral(np.array([4.0, 8.0, 12.0, 16.0]), np.ones(4), ["DEF"] * 4, UMBRALES)
    assert (np.diff(p) > 0).all()
    assert 0.0 <= p.min() and p.max() <= 1.0


def test_la_probabilidad_crece_con_los_minutos():
    m = DefConModel()
    p = m.p_umbral(np.full(4, 10.0), np.array([0.25, 0.5, 0.75, 1.0]), ["DEF"] * 4, UMBRALES)
    assert (np.diff(p) > 0).all()


def test_al_mismo_conteo_el_mediocampista_lo_tiene_mas_dificil():
    """DEF cruza en 10, MID en 12: con la misma tasa el DEF debe salir mejor parado."""
    m = DefConModel()
    p = m.p_umbral(np.array([11.0, 11.0]), np.ones(2), ["DEF", "MID"], UMBRALES)
    assert p[0] > p[1]


# ------------------------------------------------------------------ dispersion

def test_la_dispersion_se_estima_y_queda_en_rango():
    m = DefConModel().fit(muestra())
    assert not m.sin_datos
    for pos in ("DEF", "MID", "FWD"):
        assert DISPERSION_MIN <= m.dispersion[pos] <= DISPERSION_MAX


def test_sin_la_columna_el_modelo_lo_declara_en_vez_de_inventar():
    """En el backtest ciego de 2025-26 la regla no existia antes. Eso se dice."""
    d = muestra().drop(columns=["defensive_contribution"])
    m = DefConModel().fit(d)
    assert m.sin_datos
    assert "defensive_contribution" in m.metadata["aviso"]
    assert all(v == DISPERSION_POR_DEFECTO for v in m.dispersion.values())


def test_la_binomial_negativa_pone_mas_masa_en_la_cola_que_poisson():
    """Es la razon de usarla. Con Poisson, P(>= umbral) queda corta en la cola alta."""
    from scipy.stats import poisson
    m = DefConModel(dispersion={"DEF": 4.0}, sin_datos=False)
    mu = 6.0
    nb = m.p_umbral(np.array([mu]), np.ones(1), ["DEF"], UMBRALES)[0]
    po = float(poisson.sf(UMBRALES[Position.DEF] - 1, mu))
    assert nb > po


# ---------------------------------------------------------------- AC-WP005-004

@pytest.mark.slow
def test_calibracion_sobre_la_ventana_real_de_2025_26():
    """AC-WP005-004: ECE <= 0,08 en held-out temporal, reportado por posicion."""
    from mova_fpl.data.store import Store

    store = Store()
    ventana = [(store.as_of("2025-26", gw), store.results("2025-26", gw))
               for gw in range(20, 39)]
    r = evaluate(DefConModel(), ventana, UMBRALES)
    assert r["n"] > 3000, f"muestra insuficiente: {r['n']}"
    assert r["ece"] <= 0.08, f"ECE {r['ece']:.4f} por encima del umbral"
    for pos, s in r["por_posicion"].items():
        assert s["ece"] <= 0.12, f"{pos}: ECE {s['ece']:.4f}"
