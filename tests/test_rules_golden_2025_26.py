"""WP-002 / AC-WP002-001,-002: fidelidad del motor contra 29.747 actuaciones reales.

Recomputa total_points desde estadisticas crudas y lo contrasta con lo observado.
Es el test que convierte "creemos que entendimos las reglas" en un numero.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from mova_fpl.rules import PlayerStats, Position, score

ROOT = Path(__file__).resolve().parents[1]
CSV = ROOT / "data" / "raw" / "fpl_seasons" / "merged_gw_2025-26.csv"
UMBRAL = 0.99


def _stats(row) -> PlayerStats:
    return PlayerStats(
        position=Position.parse(row.position), minutes=int(row.minutes),
        goals_scored=int(row.goals_scored), assists=int(row.assists),
        clean_sheets=int(row.clean_sheets), goals_conceded=int(row.goals_conceded),
        own_goals=int(row.own_goals), penalties_saved=int(row.penalties_saved),
        penalties_missed=int(row.penalties_missed), yellow_cards=int(row.yellow_cards),
        red_cards=int(row.red_cards), saves=int(row.saves), bonus=int(row.bonus),
        defensive_contribution=int(row.defensive_contribution),
    )


@pytest.fixture(scope="module")
def resultado():
    df = pd.read_csv(CSV, low_memory=False, encoding_errors="replace").drop_duplicates()
    filas, exactas, fallos = 0, 0, []
    for row in df.itertuples(index=False):
        filas += 1
        got = score(_stats(row), "2025-26").total
        if got == int(row.total_points):
            exactas += 1
        else:
            fallos.append({"name": row.name, "pos": row.position, "gw": int(row.GW),
                           "min": int(row.minutes), "real": int(row.total_points), "calc": got})
    return filas, exactas, fallos


def test_fidelidad_supera_umbral(resultado):
    filas, exactas, fallos = resultado
    ratio = exactas / filas
    assert ratio >= UMBRAL, (
        f"fidelidad {ratio:.4%} < {UMBRAL:.0%} ({len(fallos):,} discrepancias de {filas:,})"
    )


def test_discrepancias_estan_explicadas(resultado):
    """AC-WP002-002: una discrepancia sin causa identificada es un bloqueo."""
    _, _, fallos = resultado
    if not fallos:
        return
    muestra = fallos[:20]
    pytest.fail(
        f"{len(fallos)} discrepancias sin clasificar. Cada una debe tener causa "
        f"documentada antes de aprobar el workpack. Muestra: {muestra}"
    )


def test_desglose_suma_el_total(resultado):
    df = pd.read_csv(CSV, low_memory=False, encoding_errors="replace").drop_duplicates().head(2000)
    for row in df.itertuples(index=False):
        b = score(_stats(row), "2025-26")
        assert b.total == sum(v for k, v in b.as_dict().items() if k != "total")


# --------------------------------------------------- casos construidos a mano

def test_delantero_con_gol_y_60_minutos():
    b = score(PlayerStats(Position.FWD, minutes=90, goals_scored=1), "2025-26")
    assert (b.appearance, b.goals, b.total) == (2, 4, 6)


def test_defensa_con_porteria_a_cero():
    b = score(PlayerStats(Position.DEF, minutes=90, clean_sheets=1), "2025-26")
    assert (b.appearance, b.clean_sheet, b.total) == (2, 4, 6)


def test_porteria_a_cero_exige_60_minutos():
    b = score(PlayerStats(Position.DEF, minutes=59, clean_sheets=1), "2025-26")
    assert b.clean_sheet == 0 and b.appearance == 1


def test_portero_atajadas_en_tramos_de_tres():
    for saves, pts in ((2, 0), (3, 1), (5, 1), (6, 2)):
        assert score(PlayerStats(Position.GKP, minutes=90, saves=saves), "2025-26").saves == pts


def test_goles_encajados_solo_penalizan_gkp_y_def():
    assert score(PlayerStats(Position.DEF, minutes=90, goals_conceded=3), "2025-26").goals_conceded == -1
    assert score(PlayerStats(Position.GKP, minutes=90, goals_conceded=4), "2025-26").goals_conceded == -2
    assert score(PlayerStats(Position.MID, minutes=90, goals_conceded=4), "2025-26").goals_conceded == 0


def test_defcon_umbral_por_posicion():
    # DEF: umbral 10
    assert score(PlayerStats(Position.DEF, minutes=90, defensive_contribution=9), "2025-26").defensive_contribution == 0
    assert score(PlayerStats(Position.DEF, minutes=90, defensive_contribution=10), "2025-26").defensive_contribution == 2
    # MID y FWD: umbral 12
    assert score(PlayerStats(Position.MID, minutes=90, defensive_contribution=11), "2025-26").defensive_contribution == 0
    assert score(PlayerStats(Position.MID, minutes=90, defensive_contribution=12), "2025-26").defensive_contribution == 2
    # GKP no es elegible
    assert score(PlayerStats(Position.GKP, minutes=90, defensive_contribution=30), "2025-26").defensive_contribution == 0


def test_sin_dato_de_defcon_no_se_inventan_puntos():
    b = score(PlayerStats(Position.DEF, minutes=90, defensive_contribution=None), "2025-26")
    assert b.defensive_contribution == 0


def test_temporadas_previas_no_tienen_reglas():
    with pytest.raises(ValueError, match="no hay reglas"):
        score(PlayerStats(Position.DEF, minutes=90), "2024-25")
