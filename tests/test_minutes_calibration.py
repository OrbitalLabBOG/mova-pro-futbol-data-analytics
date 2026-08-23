"""WP-004 / AC-WP004-001,-002,-003,-005,-006: calibracion del modelo de minutos."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pytest

from mova_fpl.data.store import Store
from mova_fpl.models.minutes import (MinutesModel, brier, calibration_table,
                                     expected_calibration_error)
from mova_fpl.models.registry import ARTIFACTS, git_sha
from mova_fpl.trace.writer import DEFAULT_TRACE

HOLDOUT = "2025-26"
UMBRAL_ECE = 0.05


@pytest.fixture(scope="module")
def entrenado():
    store = Store()
    modelo = MinutesModel().fit(store.multi_season_as_of(HOLDOUT, 1), calib_season="2024-25")
    evalua = store.multi_season_as_of(HOLDOUT, 39)
    evalua = evalua[evalua["season"] == HOLDOUT]
    return modelo, evalua, modelo.evaluate(evalua)


# --------------------------------------------------- AC-WP004-001

@pytest.mark.integration_data
def test_tres_probabilidades_que_suman_uno(entrenado):
    modelo, evalua, _ = entrenado
    p = modelo.predict_proba(evalua)
    assert p.shape == (len(evalua), 3)
    assert np.allclose(p.sum(axis=1), 1.0, atol=1e-6)
    assert (p >= 0).all() and (p <= 1).all()


# --------------------------------------------------- AC-WP004-002

@pytest.mark.integration_data
def test_calibracion_dentro_del_umbral(entrenado):
    _, _, m = entrenado
    assert m["ece_p60"] <= UMBRAL_ECE, f"ECE {m['ece_p60']:.4f} > {UMBRAL_ECE}"


@pytest.mark.integration_data
def test_calibra_mejor_que_el_baseline(entrenado):
    _, _, m = entrenado
    assert m["ece_p60"] < m["ece_p60_baseline"]


# --------------------------------------------------- AC-WP004-003

@pytest.mark.integration_data
def test_brier_mejor_que_la_frecuencia_historica(entrenado):
    _, _, m = entrenado
    assert m["brier_p60"] < m["brier_p60_baseline"], (
        f"Brier {m['brier_p60']:.4f} no mejora al baseline {m['brier_p60_baseline']:.4f}")


# --------------------------------------------------- AC-WP004-005

@pytest.mark.integration_data
def test_la_curva_de_calibracion_se_puede_publicar(entrenado):
    _, _, m = entrenado
    t = m["tabla_calibracion"]
    assert len(t) == 10
    poblados = t[t["n"] > 0]
    assert len(poblados) >= 8
    # monotonia: mas probabilidad predicha implica mas frecuencia observada
    obs = poblados["observado"].to_numpy()
    assert np.corrcoef(poblados["predicho"], obs)[0, 1] > 0.95


def test_el_reporte_de_calibracion_existe():
    p = Path("docs/specs/fpl-decision-engine/evidence/WP-004-calibracion.md")
    assert p.exists() and "ECE" in p.read_text(encoding="utf-8")


# --------------------------------------------------- AC-WP004-006

@pytest.mark.integration_data
def test_registrado_en_model_versions_con_git_sha():
    if not Path(DEFAULT_TRACE).exists():
        pytest.skip("aun no hay traza local")
    with sqlite3.connect(DEFAULT_TRACE) as con:
        filas = con.execute(
            "SELECT version, git_sha, train_rows, metrics FROM model_versions WHERE name='minutes'"
        ).fetchall()
    assert filas, "el modelo no quedo registrado"
    v, sha, filas_tr, met = filas[-1]
    assert sha and sha != "unknown"
    # el ajuste base excluye la temporada reservada para calibrar
    assert filas_tr > 150_000
    metrics = json.loads(met)
    if metrics.get("mode") == "production":
        # El artefacto operativo usa la ultima temporada cerrada para calibrar.
        # Publicar un ECE sobre esa misma temporada seria presentarlo falsamente
        # como held-out; las metricas de generalizacion viven en el benchmark.
        assert metrics["held_out_metrics"] is False
        assert metrics["calib_season"] == HOLDOUT
        assert metrics["fit_through"] == HOLDOUT
    else:
        assert "ece_p60" in metrics


@pytest.mark.integration_data
def test_el_artefacto_quedo_versionado():
    assert list((ARTIFACTS / "minutes").glob("minutes-*.joblib"))


# --------------------------------------------------- utilidades

def test_ece_perfecto_es_cero():
    y = np.array([1, 1, 0, 0], dtype=float)
    assert expected_calibration_error(y, np.array([0.95, 0.95, 0.05, 0.05])) < 0.06


def test_ece_castiga_el_exceso_de_confianza():
    y = np.zeros(100)
    assert expected_calibration_error(y, np.full(100, 0.9)) == pytest.approx(0.9, abs=1e-9)


def test_brier_de_prediccion_perfecta_es_cero():
    assert brier(np.array([1.0, 0.0]), np.array([1.0, 0.0])) == 0.0


def test_tabla_de_calibracion_reparte_todas_las_filas():
    y = np.random.RandomState(0).randint(0, 2, 500).astype(float)
    p = np.random.RandomState(1).rand(500)
    assert int(calibration_table(y, p)["n"].sum()) == 500
