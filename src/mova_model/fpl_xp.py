"""Motor Determinista de Expected Points (xP) para Fantasy Premier League.

Implementa la fórmula SOTA descompuesta en:
  xP = xMin * [ BasePts/90 + xG90 * PtsGoal + xA90 * 3 + xCS * PtsCS + xBPS - Penalizaciones ]
"""
import sqlite3
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, Any, List, Optional

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "mundial.db"


class FPLxPEngine:
    """Motor determinista de predicción de Expected Points (xP)."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path

    def load_player_features(self, target_gw: int = 38) -> pd.DataFrame:
        """Carga los datos históricos y características acumuladas antes de la Gameweek objetivo."""
        conn = sqlite3.connect(self.db_path)
        query = """
        WITH opta_agg AS (
            SELECT 
                player_name,
                COUNT(CASE WHEN is_shot = 1 THEN 1 END) AS opta_shots,
                COUNT(CASE WHEN qualifiers LIKE '%KeyPass%' THEN 1 END) AS opta_key_passes,
                COUNT(CASE WHEN x >= 83 AND y >= 21 AND y <= 79 THEN 1 END) AS opta_box_touches,
                COUNT(CASE WHEN event_type = 'Tackle' THEN 1 END) AS opta_tackles
            FROM events
            WHERE source = 'whoscored_pl' AND player_name IS NOT NULL
            GROUP BY player_name
        )
        SELECT 
            ph.player_id,
            p.web_name AS player_name,
            p.element_type,
            p.now_cost / 10.0 AS price,
            t.name AS team_name,
            t.short_name AS team_short,
            ph.gameweek,
            ph.opponent_team,
            opt.short_name AS opponent_short,
            opt.strength_defence_home,
            opt.strength_defence_away,
            ph.was_home,
            ph.minutes,
            ph.total_points,
            ph.goals_scored,
            ph.assists,
            ph.clean_sheets,
            ph.expected_goals,
            ph.expected_assists,
            ph.influence,
            ph.creativity,
            ph.threat,
            ph.value,
            ph.selected,
            COALESCE(oa.opta_shots, 0) AS opta_shots,
            COALESCE(oa.opta_key_passes, 0) AS opta_key_passes,
            COALESCE(oa.opta_box_touches, 0) AS opta_box_touches,
            COALESCE(oa.opta_tackles, 0) AS opta_tackles
        FROM fpl_player_history ph
        JOIN fpl_players p ON p.id = ph.player_id
        LEFT JOIN fpl_teams t ON t.id = p.team_id
        LEFT JOIN fpl_teams opt ON opt.id = ph.opponent_team
        LEFT JOIN opta_agg oa ON (oa.player_name = p.web_name OR oa.player_name = p.first_name || ' ' || p.second_name)
        ORDER BY ph.player_id, ph.gameweek
        """
        df = pd.read_sql_query(query, conn)
        conn.close()
        return df

    def calculate_xp(self, df: pd.DataFrame, decay_factor: float = 0.85) -> pd.DataFrame:
        """Calcula el xP determinista SOTA descompuesto para cada jugador y gameweek."""
        df = df.sort_values(["player_id", "gameweek"]).copy()

        # Puntos por gol según posición (GKP:6, DEF:6, MID:5, FWD:4)
        goal_pts_map = {1: 6.0, 2: 6.0, 3: 5.0, 4: 4.0}
        cs_pts_map = {1: 4.0, 2: 4.0, 3: 1.0, 4: 0.0}

        df["pts_per_goal"] = df["element_type"].map(goal_pts_map)
        df["pts_per_cs"] = df["element_type"].map(cs_pts_map)

        # Minutos esperados (xMin) basados en promedio móvil exponencial
        df["xmin"] = df.groupby("player_id")["minutes"].transform(
            lambda x: x.shift(1).ewm(alpha=1-decay_factor, min_periods=1).mean()
        ).fillna(60.0)

        # Probabilidad de jugar >= 60 minutos
        df["prob_60_min"] = (df["xmin"] / 90.0).clip(0, 1)

        # xG90 y xA90 exponenciales móviles
        df["xg_exp"] = df.groupby("player_id")["expected_goals"].transform(
            lambda x: x.shift(1).ewm(alpha=1-decay_factor, min_periods=1).mean()
        ).fillna(0.05)

        df["xa_exp"] = df.groupby("player_id")["expected_assists"].transform(
            lambda x: x.shift(1).ewm(alpha=1-decay_factor, min_periods=1).mean()
        ).fillna(0.05)

        # ICT Index esperado
        df["ict_exp"] = df.groupby("player_id")["influence"].transform(
            lambda x: (x.shift(1) + df.loc[x.index, "creativity"].shift(1) + df.loc[x.index, "threat"].shift(1)).ewm(alpha=1-decay_factor, min_periods=1).mean()
        ).fillna(10.0)

        # Estimación de Clean Sheet (xCS) aproximada por dificultad del rival
        df["opp_def_strength"] = np.where(
            df["was_home"] == 1,
            df["strength_defence_away"].fillna(1000) / 1000.0,
            df["strength_defence_home"].fillna(1000) / 1000.0
        )
        df["xcs"] = (0.35 / df["opp_def_strength"]).clip(0.05, 0.65)

        # Componentes de puntos
        df["xp_appearance"] = np.where(df["xmin"] >= 60, 2.0, np.where(df["xmin"] > 0, 1.0, 0.0))
        df["xp_goals"] = df["xg_exp"] * df["pts_per_goal"]
        df["xp_assists"] = df["xa_exp"] * 3.0
        df["xp_cs"] = df["xcs"] * df["pts_per_cs"]
        df["xp_bonus"] = (df["ict_exp"] / 50.0).clip(0, 1.5)

        # Suma total de xP determinista
        df["xp_predicted"] = (
            (df["xmin"] / 90.0) * (df["xp_appearance"] + df["xp_goals"] + df["xp_assists"] + df["xp_cs"] + df["xp_bonus"])
        ).round(2)

        return df


def get_gameweek_xp_matrix(gameweek: int, db_path: Path = DB_PATH) -> pd.DataFrame:
    """Función de alto nivel para obtener la matriz de xP de una Gameweek dada."""
    engine = FPLxPEngine(db_path)
    df = engine.load_player_features(gameweek)
    df_calc = engine.calculate_xp(df)
    gw_df = df_calc[df_calc["gameweek"] == gameweek].copy()
    return gw_df.sort_values("xp_predicted", ascending=False)
