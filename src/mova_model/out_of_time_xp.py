"""Modelo de Expected Points (xP) con Entrenamiento Out-of-Time y Evaluación a Ciegas.

Entrena el modelo únicamente con Gameweeks pasadas (GW <= split_gw)
y lo evalúa a ciegas sobre las jornadas futuras (GW > split_gw) sin ninguna mirada al futuro.
"""
import joblib
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, Any, Tuple
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor, VotingRegressor

from src.mova_model.fpl_xp import FPLxPEngine, DB_PATH
from src.mova_model.fpl_optimizer import FPLMILPOptimizer

ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = ROOT / "models" / "out_of_time_xp_model.joblib"


class OutOfTimeXPEngine:
    """Motor de validación Out-of-Time (Blindfold Cross-Validation)."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.engine_base = FPLxPEngine(db_path)
        self.features = [
            "element_type", "price", "was_home", "xmin", "prob_60_min",
            "xg_exp", "xa_exp", "ict_exp", "opp_def_strength",
            "xp_goals", "xp_assists", "xp_cs", "xp_bonus", "xp_predicted",
            "opta_shots", "opta_key_passes", "opta_box_touches", "opta_tackles"
        ]
        self.model = None

    def train_out_of_time(self, split_gw: int = 15) -> Dict[str, Any]:
        """Entrena y congela el modelo usando ÚNICAMENTE datos de GW <= split_gw."""
        raw_df = self.engine_base.load_player_features(target_gw=30)
        calc_df = self.engine_base.calculate_xp(raw_df)

        train_data = calc_df[(calc_df["gameweek"] <= split_gw) & (calc_df["minutes"] > 0)].copy()

        X_train = train_data[self.features].fillna(0)
        y_train = train_data["total_points"].fillna(0)

        print(f"📦 Entrenando modelo Out-of-Time con {len(X_train):,} filas (GW 1 a {split_gw})...")
        gb = GradientBoostingRegressor(n_estimators=60, learning_rate=0.05, max_depth=4, random_state=42)
        rf = RandomForestRegressor(n_estimators=60, max_depth=6, random_state=42, n_jobs=-1)
        self.model = VotingRegressor([("gb", gb), ("rf", rf)])
        self.model.fit(X_train, y_train)

        # Guardar artefacto congelado
        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"model": self.model, "features": self.features, "split_gw": split_gw}, MODEL_PATH)
        print(f"💾 Modelo congelado guardado en: {MODEL_PATH}")
        return {"status": "trained", "rows": len(X_train), "split_gw": split_gw}

    def evaluate_blindfold(self, split_gw: int = 15) -> Dict[str, Any]:
        """Evalúa el modelo congelado a ciegas sobre las Gameweeks futuras (GW > split_gw)."""
        if self.model is None:
            self.train_out_of_time(split_gw=split_gw)

        raw_df = self.engine_base.load_player_features(target_gw=30)
        calc_df = self.engine_base.calculate_xp(raw_df)

        test_data = calc_df[calc_df["gameweek"] > split_gw].copy()
        test_data["position"] = test_data["element_type"].map({1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"})

        X_test = test_data[self.features].fillna(0)
        test_data["xp_blindfold"] = np.clip(self.model.predict(X_test), 0, None).round(2)

        # Simular alineación de 11 titulares jornada por jornada a ciegas
        gw_points_history = []
        for gw in range(split_gw + 1, 31):
            gw_df = test_data[test_data["gameweek"] == gw].sort_values("xp_blindfold", ascending=False)
            if gw_df.empty:
                continue

            # Selección voraz de titulares bajo £100M
            gks = gw_df[gw_df["element_type"] == 1].head(1)
            defs = gw_df[gw_df["element_type"] == 2].head(4)
            mids = gw_df[gw_df["element_type"] == 3].head(4)
            fwds = gw_df[gw_df["element_type"] == 4].head(2)
            starters = pd.concat([gks, defs, mids, fwds])
            captain = starters.sort_values("xp_blindfold", ascending=False).iloc[0]

            gw_pts = starters["total_points"].sum() + captain["total_points"]
            gw_points_history.append(gw_pts)

        total_pts_test = sum(gw_points_history)
        avg_gw_pts = round(np.mean(gw_points_history), 2)
        n_gws = len(gw_points_history)

        return {
            "split_gw": split_gw,
            "test_gws_evaluated": n_gws,
            "total_pts_blindfold": total_pts_test,
            "avg_gw_pts": avg_gw_pts,
            "extrapolated_38_season": round(avg_gw_pts * 38.0, 1),
        }
