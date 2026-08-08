"""WP-004 / AC-WP004-004: el modelo de minutos no puede ver el futuro."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mova_fpl.data.identity import player_key
from mova_fpl.data.store import Store
from mova_fpl.models.features.minutes_features import FEATURES, build


@pytest.fixture(scope="module")
def store() -> Store:
    return Store()


def test_las_features_solo_miran_al_pasado():
    """Construidas con shift(1): la primera fila de un jugador no tiene historial."""
    df = pd.DataFrame({
        "player_key": ["a"] * 4, "season": ["2025-26"] * 4, "gw": [1, 2, 3, 4],
        "fixture": [1, 2, 3, 4], "minutes": [90, 0, 45, 90], "starts": [1, 0, 0, 1],
        "value": [50] * 4, "position": ["MID"] * 4, "was_home": [1, 0, 1, 0],
    })
    d = build(df)
    assert pd.isna(d.loc[0, "min_anterior"]), "la primera observacion no puede tener pasado"
    assert d.loc[1, "min_anterior"] == 90
    assert d.loc[2, "min_anterior"] == 0
    assert d.loc[3, "min_anterior"] == 45
    assert list(d["n_prev"]) == [0, 1, 2, 3]


def test_el_objetivo_no_esta_entre_las_features():
    prohibidas = {"minutes", "minutos", "y", "jugo", "jugo_60", "total_points"}
    assert not (set(FEATURES) & prohibidas)


def test_cambiar_el_futuro_no_altera_el_presente():
    """Prueba dura: modificar filas posteriores no puede mover las features previas."""
    base = pd.DataFrame({
        "player_key": ["a"] * 5, "season": ["2025-26"] * 5, "gw": [1, 2, 3, 4, 5],
        "fixture": [1, 2, 3, 4, 5], "minutes": [90, 90, 90, 0, 0], "starts": [1] * 5,
        "value": [50] * 5, "position": ["MID"] * 5, "was_home": [1] * 5,
    })
    alterado = base.copy()
    alterado.loc[3:, "minutes"] = [90, 90]          # se cambia SOLO el futuro
    a = build(base)[FEATURES].iloc[:3].fillna(-999)
    b = build(alterado)[FEATURES].iloc[:3].fillna(-999)
    pd.testing.assert_frame_equal(a, b)


def test_la_racha_de_ceros_es_causal():
    df = pd.DataFrame({
        "player_key": ["a"] * 5, "season": ["2025-26"] * 5, "gw": [1, 2, 3, 4, 5],
        "fixture": [1, 2, 3, 4, 5], "minutes": [90, 0, 0, 0, 90], "starts": [1] * 5,
        "value": [50] * 5, "position": ["MID"] * 5, "was_home": [1] * 5,
    })
    assert list(build(df)["racha_ceros"]) == [0.0, 0.0, 1.0, 2.0, 3.0]


def test_el_historial_cruza_temporadas_por_player_key(store: Store):
    """element se reasigna cada anio; player_key es la identidad estable."""
    df = store.multi_season_as_of("2025-26", 39, ["player_key", "element", "season", "gw",
                                                  "fixture", "minutes", "value", "position",
                                                  "was_home", "starts"])
    d = build(df)
    veteranos = d[(d["season"] == "2025-26") & (d["gw"] == 1) & (d["n_prev"] > 30)]
    assert len(veteranos) > 100, "los veteranos deben llegar a la GW1 con historial acumulado"


def test_el_entrenamiento_no_toca_la_temporada_holdout(store: Store):
    """as_of(holdout, 1) devuelve cero filas de esa temporada."""
    entrena = store.multi_season_as_of("2025-26", 1)
    assert (entrena["season"] == "2025-26").sum() == 0
    assert set(entrena["season"].unique()) == set(
        ["2016-17", "2017-18", "2018-19", "2019-20", "2020-21",
         "2021-22", "2022-23", "2023-24", "2024-25"])
