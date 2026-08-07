"""Script de Entrenamiento y Versionamiento de Modelos xP (v1, v2, v3 Ensemble).

Entrena y guarda 3 versiones de modelos en `models/`:
  - `v1_baseline_xp.joblib` (Modelo determinista sin ML)
  - `v2_gradient_boosting_xp.joblib` (Gradient Boosting Regressor)
  - `v3_ensemble_xp.joblib` (Ensamble Gradient Boosting + Random Forest con Opta Features)
"""
import sys
import joblib
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor, VotingRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, mean_squared_error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.mova_model.fpl_xp import FPLxPEngine, DB_PATH

MODEL_DIR = ROOT / "models"


def train_and_version_all():
    print("🚀 Cargando dataset de Ground Truth desde SQLite...")
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    engine = FPLxPEngine(DB_PATH)
    raw_df = engine.load_player_features(target_gw=38)
    calc_df = engine.calculate_xp(raw_df)

    df = calc_df[calc_df["minutes"] > 0].copy()

    features = [
        "element_type", "price", "was_home", "xmin", "prob_60_min",
        "xg_exp", "xa_exp", "ict_exp", "opp_def_strength",
        "xp_goals", "xp_assists", "xp_cs", "xp_bonus", "xp_predicted",
        "opta_shots", "opta_key_passes", "opta_box_touches", "opta_tackles"
    ]
    target = "total_points"

    X = df[features].fillna(0)
    y = df[target].fillna(0)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, shuffle=True
    )

    print(f"📊 Rows: Train={len(X_train):,}, Test={len(X_test):,}")

    # 1. Version v1 (Baseline Determinista)
    print("\n📦 Versionando v1: Baseline Determinista...")
    joblib.dump({
        "model": None,
        "features": features,
        "metadata": {
            "version": "v1.0.0",
            "type": "Deterministic Empirical Formula",
            "created_at": datetime.now().isoformat()
        }
    }, MODEL_DIR / "v1_baseline_xp.joblib")

    # 2. Version v2 (Gradient Boosting)
    print("🧠 Entrenando v2: Gradient Boosting Regressor...")
    gb_model = GradientBoostingRegressor(
        n_estimators=150, learning_rate=0.05, max_depth=5, random_state=42
    )
    gb_model.fit(X_train, y_train)
    gb_preds = gb_model.predict(X_test)
    gb_mae = mean_absolute_error(y_test, gb_preds)
    gb_rmse = np.sqrt(mean_squared_error(y_test, gb_preds))

    joblib.dump({
        "model": gb_model,
        "features": features,
        "metadata": {
            "version": "v2.0.0",
            "type": "Gradient Boosting Regressor",
            "mae": round(gb_mae, 4),
            "rmse": round(gb_rmse, 4),
            "created_at": datetime.now().isoformat()
        }
    }, MODEL_DIR / "v2_gradient_boosting_xp.joblib")
    print(f"   ✓ v2 Guardado. MAE: {gb_mae:.3f} | RMSE: {gb_rmse:.3f}")

    # 3. Version v3 (Ensemble Voting Regressor: GB + RF)
    print("🔥 Entrenando v3: Ensemble Regressor (GB + Random Forest + Opta Features)...")
    rf_model = RandomForestRegressor(
        n_estimators=200, max_depth=8, random_state=42, n_jobs=-1
    )
    ensemble_model = VotingRegressor(
        estimators=[("gb", gb_model), ("rf", rf_model)]
    )
    ensemble_model.fit(X_train, y_train)
    ens_preds = ensemble_model.predict(X_test)
    ens_mae = mean_absolute_error(y_test, ens_preds)
    ens_rmse = np.sqrt(mean_squared_error(y_test, ens_preds))

    joblib.dump({
        "model": ensemble_model,
        "features": features,
        "metadata": {
            "version": "v3.0.0-ensemble",
            "type": "Voting Ensemble (Gradient Boosting + Random Forest)",
            "mae": round(ens_mae, 4),
            "rmse": round(ens_rmse, 4),
            "created_at": datetime.now().isoformat()
        }
    }, MODEL_DIR / "v3_ensemble_xp.joblib")

    # Copiar v3 a fpl_xp_model.joblib por compatibilidad
    joblib.dump({
        "model": ensemble_model,
        "features": features,
        "metadata": {
            "version": "v3.0.0-ensemble",
            "mae": round(ens_mae, 4),
            "rmse": round(ens_rmse, 4)
        }
    }, MODEL_DIR / "fpl_xp_model.joblib")

    print(f"   ✓ v3 Ensemble Guardado. MAE: {ens_mae:.3f} | RMSE: {ens_rmse:.3f}")
    print("\n🎉 Todos los modelos han sido versionados exitosamente en `models/`.")


if __name__ == "__main__":
    train_and_version_all()
