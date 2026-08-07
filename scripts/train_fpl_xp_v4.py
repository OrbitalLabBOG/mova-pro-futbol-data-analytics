"""Script de Entrenamiento del Modelo v4 Ultra Ensemble (train_fpl_xp_v4.py).

Entrena un modelo ensamble calibrado de alta precisión (HistGradientBoosting + RandomForest + Ridge)
con 18 features temporales y espaciales Opta. Guarda `models/v4_ultra_ensemble.joblib`.
"""
import sys
import joblib
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor, VotingRegressor
from sklearn.linear_model import Ridge
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, mean_squared_error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.mova_model.fpl_xp import FPLxPEngine, DB_PATH

MODEL_DIR = ROOT / "models"
MODEL_PATH = MODEL_DIR / "v4_ultra_ensemble.joblib"


def train_v4_ultra():
    print("🚀 Cargando datos con Features v4 (Espaciales Opta + Temporales Short/Long)...")
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    engine = FPLxPEngine(DB_PATH)
    raw_df = engine.load_player_features(target_gw=30)
    calc_df = engine.calculate_xp(raw_df)

    df = calc_df[calc_df["minutes"] > 0].copy()

    features = [
        "element_type", "price", "was_home", "xmin", "prob_60_min", "min_volatility",
        "xg_exp", "xa_exp", "xg_exp_5", "xa_exp_5", "ict_exp", "opp_def_strength",
        "xp_goals", "xp_assists", "xp_cs", "xp_bonus", "xp_predicted",
        "opta_shots", "opta_key_passes", "opta_box_touches", "opta_tackles", "opta_box_touch_ratio"
    ]
    target = "total_points"

    X = df[features].fillna(0)
    y = df[target].fillna(0)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, shuffle=True
    )

    print(f"📊 Dataset v4 Ultra: Train={len(X_train):,}, Test={len(X_test):,}")
    print("🔥 Entrenando Ensamble v4 Ultra (HistGB + Random Forest + Ridge)...")

    hgb = HistGradientBoostingRegressor(max_iter=150, learning_rate=0.04, max_depth=6, random_state=42)
    rf = RandomForestRegressor(n_estimators=250, max_depth=9, random_state=42, n_jobs=-1)
    ridge = Ridge(alpha=10.0)

    model = VotingRegressor(estimators=[("hgb", hgb), ("rf", rf), ("ridge", ridge)])
    model.fit(X_train, y_train)

    preds = model.predict(X_test)
    mae = mean_absolute_error(y_test, preds)
    rmse = np.sqrt(mean_squared_error(y_test, preds))

    print(f"✅ Modelo v4 Ultra Entrenado:")
    print(f"   - MAE en Test:  {mae:.4f} pts")
    print(f"   - RMSE en Test: {rmse:.4f} pts")

    # Guardar artefacto
    joblib.dump({
        "model": model,
        "features": features,
        "metadata": {
            "version": "v4.0.0-ultra",
            "type": "Voting Ensemble (HistGB + RF + Ridge)",
            "mae": round(mae, 4),
            "rmse": round(rmse, 4),
            "created_at": datetime.now().isoformat()
        }
    }, MODEL_PATH)

    # Copiar a fpl_xp_model.joblib y v3 para inferencia transparente
    joblib.dump({
        "model": model,
        "features": features,
        "metadata": {"version": "v4.0.0-ultra", "mae": round(mae, 4)}
    }, MODEL_DIR / "fpl_xp_model.joblib")

    joblib.dump({
        "model": model,
        "features": features,
        "metadata": {"version": "v4.0.0-ultra", "mae": round(mae, 4)}
    }, MODEL_DIR / "v3_ensemble_xp.joblib")

    print(f"💾 Artefacto guardado en: {MODEL_PATH}")


if __name__ == "__main__":
    train_v4_ultra()
