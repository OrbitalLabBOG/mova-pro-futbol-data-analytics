"""Entrenamiento y Calibración del Modelo Predictivo de Expected Points (xP).

Entrena un modelo de regresión Gradient Boosting / Random Forest sobre 19,375 filas
de Ground Truth de `fpl_player_history` y guarda los artefactos en `models/fpl_xp_model.joblib`.
"""
import sys
import sqlite3
import joblib
import pandas as pd
import numpy as np
from pathlib import Path
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, mean_squared_error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.mova_model.fpl_xp import FPLxPEngine, DB_PATH
MODEL_DIR = ROOT / "models"
MODEL_PATH = MODEL_DIR / "fpl_xp_model.joblib"


def train_xp_model():
    print("🚀 Cargando datos de Ground Truth desde SQLite...")
    engine = FPLxPEngine(DB_PATH)
    raw_df = engine.load_player_features(target_gw=38)
    calc_df = engine.calculate_xp(raw_df)

    # Filtrar registros donde hubo minutos o datos suficientes
    df = calc_df[calc_df["minutes"] > 0].copy()

    features = [
        "element_type", "price", "was_home", "xmin", "prob_60_min",
        "xg_exp", "xa_exp", "ict_exp", "opp_def_strength",
        "xp_goals", "xp_assists", "xp_cs", "xp_bonus", "xp_predicted"
    ]
    target = "total_points"

    X = df[features].fillna(0)
    y = df[target].fillna(0)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, shuffle=True
    )

    print(f"📊 Dataset de entrenamiento: {len(X_train):,} filas | Test: {len(X_test):,} filas.")
    print("🧠 Entrenando Gradient Boosting Regressor...")

    model = GradientBoostingRegressor(
        n_estimators=150,
        learning_rate=0.05,
        max_depth=5,
        random_state=42
    )
    model.fit(X_train, y_train)

    # Evaluación en test
    preds = model.predict(X_test)
    mae = mean_absolute_error(y_test, preds)
    rmse = np.sqrt(mean_squared_error(y_test, preds))

    print(f"✅ Modelo entrenado exitosamente:")
    print(f"   - MAE en Test:  {mae:.3f} pts")
    print(f"   - RMSE en Test: {rmse:.3f} pts")

    # Guardar modelo
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "features": features}, MODEL_PATH)
    print(f"💾 Artefacto guardado en: {MODEL_PATH}")


if __name__ == "__main__":
    train_xp_model()
