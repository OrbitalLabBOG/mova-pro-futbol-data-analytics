"""WP-001: contrato temporal del almacen (AC-WP001-001..005)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from mova_fpl.data.ingest import build, load_season_csv
from mova_fpl.data.schema import KEY, SEASONS
from mova_fpl.data.store import LeakageError, Store, assert_causal

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def store() -> Store:
    return Store()


# -------------------------------------------------- AC-WP001-001

def test_volumen_y_temporadas(store: Store):
    assert store.row_count() >= 250_000, f"solo {store.row_count():,} filas"
    assert store.seasons() == SEASONS


# -------------------------------------------------- AC-WP001-003

def test_as_of_ventana_exacta(store: Store):
    df = store.as_of("2025-26", 17)
    assert int(df["gw"].max()) == 16


@pytest.mark.parametrize("gw", range(1, 39))
def test_as_of_para_cada_gameweek(store: Store, gw: int):
    df = store.as_of("2025-26", gw)
    if df.empty:
        assert gw == 1, "solo la gameweek 1 puede devolver vacio (cold start)"
    else:
        assert int(df["gw"].max()) == gw - 1


def test_gw1_es_cold_start(store: Store):
    assert store.as_of("2025-26", 1).empty


def test_as_of_no_mezcla_temporadas(store: Store):
    assert set(store.as_of("2022-23", 20)["season"].unique()) == {"2022-23"}


def test_as_of_rechaza_entrada_invalida(store: Store):
    with pytest.raises(ValueError):
        store.as_of("2099-00", 5)
    with pytest.raises(ValueError):
        store.as_of("2025-26", 0)


def test_multi_season_respeta_ventana(store: Store):
    df = store.multi_season_as_of("2025-26", 10)
    actual = df[df["season"] == "2025-26"]
    assert int(actual["gw"].max()) == 9
    assert set(df["season"].unique()) == set(SEASONS[: SEASONS.index("2025-26") + 1])


# -------------------------------------------------- AC-WP001-004

def test_instrumentacion_detecta_acceso_futuro():
    """Un frame con observaciones futuras debe hacer fallar la corrida."""
    contaminado = pd.DataFrame({"season": ["2025-26"] * 3, "gw": [5, 6, 12], "element": [1, 2, 3]})
    with pytest.raises(LeakageError, match="LEAKAGE"):
        assert_causal(contaminado, "2025-26", 6)


def test_instrumentacion_acepta_frame_causal():
    limpio = pd.DataFrame({"season": ["2025-26"] * 2, "gw": [4, 5], "element": [1, 2]})
    assert_causal(limpio, "2025-26", 6)


def test_instrumentacion_detecta_mezcla_de_temporadas():
    mezcla = pd.DataFrame({"season": ["2025-26", "2024-25"], "gw": [3, 3], "element": [1, 2]})
    with pytest.raises(LeakageError, match="mezcla de temporadas"):
        assert_causal(mezcla, "2025-26", 6)


def test_instrumentacion_exige_columna_gw():
    with pytest.raises(LeakageError, match="sin columna"):
        assert_causal(pd.DataFrame({"element": [1]}), "2025-26", 6)


def test_sql_y_verificacion_son_independientes(store: Store, monkeypatch):
    """Si alguien rompe el WHERE del SQL, la verificacion del resultado lo atrapa."""
    original = pd.read_sql_query

    def sql_roto(sql, con, params=None):
        return original(sql.replace("gw < ?", "gw <= ?"), con, params=params)

    monkeypatch.setattr("mova_fpl.data.store.pd.read_sql_query", sql_roto)
    with pytest.raises(LeakageError):
        store.as_of("2025-26", 10)


# -------------------------------------------------- AC-WP001-005

def test_ingesta_es_idempotente(tmp_path: Path):
    db = tmp_path / "t.db"
    a = build(["2024-25"], db_path=db)
    n1 = Store(db).row_count()
    b = build(["2024-25"], db_path=db)
    n2 = Store(db).row_count()
    assert a == b and n1 == n2


def test_clave_primaria_unica():
    """La clave incluye fixture: las dobles jornadas son observaciones distintas."""
    con = sqlite3.connect(ROOT / "data" / "processed" / "fpl_canonical.db")
    cols = ", ".join(KEY)
    dup = pd.read_sql_query(
        f"SELECT COUNT(*) n FROM (SELECT {cols} FROM player_gameweek "
        f"GROUP BY {cols} HAVING COUNT(*) > 1)", con
    )["n"].iloc[0]
    con.close()
    assert int(dup) == 0


def test_dobles_jornadas_preservadas(store: Store):
    """Regresion: la clave (season, gw, element) colapsaba DGWs reales."""
    df = store.as_of("2025-26", 30)
    raya = df[(df["gw"] == 26)].groupby("element").size()
    assert (raya > 1).sum() > 0, "no quedo ninguna doble jornada en 2025-26 GW26"


# -------------------------------------------------- AC-WP001-002

def test_cobertura_reproduce_patron_conocido(store: Store):
    cov = store.coverage()
    nn = lambda season, col: int(cov.loc[season, col])  # noqa: E731

    # DefCon: solo 2025-26, primera temporada con la regla
    assert nn("2025-26", "defensive_contribution") > 0
    for s in SEASONS[:-1]:
        assert nn(s, "defensive_contribution") == 0, f"{s} no deberia tener DefCon"

    # acciones defensivas: 2016-17..2018-19 y 2025-26; hueco en el medio
    for s in ["2016-17", "2017-18", "2018-19", "2025-26"]:
        assert nn(s, "clearances_blocks_interceptions") > 0, s
    for s in ["2019-20", "2020-21", "2021-22", "2022-23", "2023-24", "2024-25"]:
        assert nn(s, "clearances_blocks_interceptions") == 0, s

    # expected goals: desde 2022-23
    for s in ["2022-23", "2023-24", "2024-25", "2025-26"]:
        assert nn(s, "expected_goals") > 0, s
    for s in SEASONS[:6]:
        assert nn(s, "expected_goals") == 0, s

    # posicion: desde 2020-21
    for s in SEASONS[:4]:
        assert nn(s, "position") == 0, s
    for s in SEASONS[4:]:
        assert nn(s, "position") > 0, s


def test_columnas_ausentes_son_null_no_cero():
    """Inventar un cero es inventar una observacion."""
    df = load_season_csv("2019-20")
    assert df["defensive_contribution"].isna().all()
    assert df["expected_goals"].isna().all()


def test_temporada_covid_conserva_gameweeks_extra(store: Store):
    """2019-20 llega a gw 47 en la numeracion del origen; son filas reales."""
    df = store.as_of("2019-20", 48)
    assert int(df["gw"].max()) == 47
