"""Esquema canonico player-gameweek.

Regla dura (REQ-F-001): una columna ausente en una temporada queda NULL, nunca 0.
Inventar un cero es inventar una observacion.
"""
from __future__ import annotations

# Clave primaria logica.
# Incluye `fixture` porque en una DOBLE JORNADA (DGW) un jugador disputa dos
# partidos dentro de la misma gameweek: son dos observaciones distintas, no un
# duplicado. Verificado en 2025-26 GW26 (Raya: fixtures 252 y 310).
KEY = ("season", "gw", "element", "fixture")

#: Columna DERIVADA, no viene del origen. Identidad estable de jugador entre
#: temporadas: `element` se reasigna cada anio (ver data/identity.py).
DERIVED = ["player_key"]

# Presentes en las 10 temporadas (2016-17 .. 2025-26)
CORE = [
    "name", "opponent_team", "was_home", "kickoff_time", "round",
    "minutes", "total_points",
    "goals_scored", "assists", "clean_sheets", "goals_conceded", "own_goals",
    "penalties_saved", "penalties_missed", "yellow_cards", "red_cards", "saves",
    "bonus", "bps", "influence", "creativity", "threat", "ict_index",
    "value", "selected", "transfers_in", "transfers_out", "transfers_balance",
    "team_a_score", "team_h_score",
]

# Disponibles solo en parte del historico. El diccionario documenta desde/hasta
# para que coverage() pueda contrastar lo esperado contra lo observado.
OPTIONAL = {
    # posicion y equipo: desde 2020-21
    "position": ("2020-21", "2025-26"),
    "team": ("2020-21", "2025-26"),
    "xp_official": ("2020-21", "2025-26"),          # columna 'xP' del origen
    # expected goals family: desde 2022-23
    "expected_goals": ("2022-23", "2025-26"),
    "expected_assists": ("2022-23", "2025-26"),
    "expected_goal_involvements": ("2022-23", "2025-26"),
    "expected_goals_conceded": ("2022-23", "2025-26"),
    "starts": ("2022-23", "2025-26"),
    # acciones defensivas: 2016-17..2018-19 y de nuevo en 2025-26 (hueco intermedio)
    "clearances_blocks_interceptions": ("2016-17|2025-26", "split"),
    "recoveries": ("2016-17|2025-26", "split"),
    "tackles": ("2016-17|2025-26", "split"),
    # DefCon: solo 2025-26, primera temporada con la regla
    "defensive_contribution": ("2025-26", "2025-26"),
    # detalle Opta antiguo: solo 2016-17..2018-19
    "key_passes": ("2016-17", "2018-19"),
    "big_chances_created": ("2016-17", "2018-19"),
    "big_chances_missed": ("2016-17", "2018-19"),
    "errors_leading_to_goal": ("2016-17", "2018-19"),
    "open_play_crosses": ("2016-17", "2018-19"),
    "dribbles": ("2016-17", "2018-19"),
    "fouls": ("2016-17", "2018-19"),
    "offside": ("2016-17", "2018-19"),
    "penalties_conceded": ("2016-17", "2018-19"),
    "winning_goals": ("2016-17", "2018-19"),
    "attempted_passes": ("2016-17", "2018-19"),
    "completed_passes": ("2016-17", "2018-19"),
    "target_missed": ("2016-17", "2018-19"),
    "tackled": ("2016-17", "2018-19"),
}

# Renombres del CSV de origen al nombre canonico
RENAME = {"GW": "gw", "xP": "xp_official"}

# Columnas del origen que NO se ingieren y por que
DROPPED = {
    "id": "id interno del origen, no estable entre temporadas",
    "kickoff_time_formatted": "redundante con kickoff_time",
    "loaned_in": "descontinuada por FPL",
    "loaned_out": "descontinuada por FPL",
    "ea_index": "descontinuada por FPL",
    "modified": "metadato del scraper, no del juego",
    "errors_leading_to_goal_attempt": "descontinuada por FPL",
    "mng_clean_sheets": "activo 'manager', solo 2024-25; fuera de alcance v1",
    "mng_draw": "activo 'manager', solo 2024-25; fuera de alcance v1",
    "mng_goals_scored": "activo 'manager', solo 2024-25; fuera de alcance v1",
    "mng_loss": "activo 'manager', solo 2024-25; fuera de alcance v1",
    "mng_underdog_draw": "activo 'manager', solo 2024-25; fuera de alcance v1",
    "mng_underdog_win": "activo 'manager', solo 2024-25; fuera de alcance v1",
    "mng_win": "activo 'manager', solo 2024-25; fuera de alcance v1",
}

ALL_COLUMNS = list(KEY) + DERIVED + CORE + list(OPTIONAL)
assert len(ALL_COLUMNS) == len(set(ALL_COLUMNS)), (
    "columnas duplicadas en el esquema: "
    f"{sorted({c for c in ALL_COLUMNS if ALL_COLUMNS.count(c) > 1})}"
)

# Columnas prohibidas como feature: son el resultado, no el insumo.
# ADR-002 cubre el leakage temporal; esta lista cubre el leakage de target.
FORBIDDEN_AS_FEATURE = frozenset({
    "total_points", "bonus", "bps", "goals_scored", "assists", "clean_sheets",
    "goals_conceded", "own_goals", "penalties_saved", "penalties_missed",
    "yellow_cards", "red_cards", "saves", "minutes", "starts",
    "defensive_contribution", "clearances_blocks_interceptions", "recoveries",
    "tackles", "team_a_score", "team_h_score", "xp_official",
    "influence", "creativity", "threat", "ict_index",
    "expected_goals", "expected_assists", "expected_goal_involvements",
    "expected_goals_conceded",
})

SEASONS = ["2016-17", "2017-18", "2018-19", "2019-20", "2020-21",
           "2021-22", "2022-23", "2023-24", "2024-25", "2025-26"]
