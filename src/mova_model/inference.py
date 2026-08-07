"""API Unificada de Inferencia de Expected Points (xP) para MOVA.

Proporciona una interfaz limpia y desacoplada para consultar predicciones de xP
por versión de modelo (v1_baseline, v2_gradient_boosting, v3_ensemble).
"""
import joblib
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, Any, Optional

from src.mova_model.fpl_xp import FPLxPEngine, DB_PATH

ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT / "models"


class FPLInferenceEngine:
    """Motor de Inferencia de Producción para modelos xP de Fantasy Premier League."""

    VERSIONS = {
        "v1": MODEL_DIR / "v1_baseline_xp.joblib",
        "v2": MODEL_DIR / "v2_gradient_boosting_xp.joblib",
        "v3": MODEL_DIR / "v3_ensemble_xp.joblib",
        "latest": MODEL_DIR / "v3_ensemble_xp.joblib",
    }

    def __init__(self, model_version: str = "latest", db_path: Path = DB_PATH):
        self.model_version = model_version
        self.db_path = db_path
        self.xp_engine = FPLxPEngine(db_path)
        self.model = None
        self.features = []
        self.metadata = {}
        self._load_model()

    def _load_model(self):
        """Carga el modelo especificado o usa el fallback determinista."""
        model_path = self.VERSIONS.get(self.model_version, self.VERSIONS["latest"])
        if model_path.exists():
            artifact = joblib.load(model_path)
            self.model = artifact.get("model")
            self.features = artifact.get("features", [])
            self.metadata = artifact.get("metadata", {})
        else:
            # Fallback a v2 si v3 aún no está creado
            fallback = MODEL_DIR / "fpl_xp_model.joblib"
            if fallback.exists():
                artifact = joblib.load(fallback)
                self.model = artifact.get("model")
                self.features = artifact.get("features", [])

    def predict_gameweek(self, gameweek: int = 30, top_n: Optional[int] = None) -> pd.DataFrame:
        """Genera la matriz completa de xP pronosticados para una Gameweek objetivo."""
        df = self.xp_engine.load_player_features(target_gw=gameweek)
        calc_df = self.xp_engine.calculate_xp(df)
        
        max_gw_avail = calc_df["gameweek"].max()
        effective_gw = min(gameweek, max_gw_avail) if max_gw_avail else gameweek
        gw_df = calc_df[calc_df["gameweek"] == effective_gw].copy()

        pos_map = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
        gw_df["position"] = gw_df["element_type"].map(pos_map)

        if self.model is not None and self.features:
            X = gw_df[self.features].fillna(0)
            gw_df["xp_model"] = self.model.predict(X)
            # Normalizar para evitar valores negativos
            gw_df["xp_final"] = gw_df["xp_model"].clip(lower=0.0).round(2)
        else:
            gw_df["xp_final"] = gw_df["xp_predicted"].clip(lower=0.0).round(2)

        gw_df = gw_df.sort_values("xp_final", ascending=False)
        if top_n:
            return gw_df.head(top_n)
        return gw_df

    def predict_player(self, player_id: int, gameweek: int) -> Dict[str, Any]:
        """Obtiene la predicción de xP y desglose táctico para un jugador específico."""
        df = self.predict_gameweek(gameweek)
        p_row = df[df["player_id"] == player_id]
        if p_row.empty:
            return {"error": f"Jugador ID {player_id} no encontrado en GW {gameweek}"}
        row = p_row.iloc[0]
        return {
            "player_id": int(row["player_id"]),
            "player_name": row["player_name"],
            "element_type": int(row["element_type"]),
            "price": float(row["price"]),
            "team": row["team_short"],
            "opponent": row["opponent_short"],
            "was_home": bool(row["was_home"]),
            "xp_final": float(row["xp_final"]),
            "xp_deterministic": float(row["xp_predicted"]),
            "xmin": float(row["xmin"]),
            "xg_exp": float(row["xg_exp"]),
            "xa_exp": float(row["xa_exp"]),
            "model_version": self.model_version,
        }

    def get_model_info(self) -> Dict[str, Any]:
        """Retorna metadatos y versión del modelo cargado."""
        return {
            "model_version": self.model_version,
            "has_trained_model": self.model is not None,
            "features_count": len(self.features),
            "features": self.features,
            "metadata": self.metadata,
        }
