"""Entrenador del Modelo Mega Multi-Temporada v5 (train_fpl_xp_v5_multi_season.py).

Entrena un modelo ensamble de ultra precisión utilizando las 224,143 filas históricas de FPL
de las 9 temporadas completas (2016/17 a 2024/25).
"""
import sys
import sqlite3
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

DB_PATH = ROOT / "data" / "mundial.db"
MODEL_DIR = ROOT / "models"
MODEL_PATH = MODEL_DIR / "v5_multi_season_ensemble.joblib"


def train_v5_multi_season():
    print("🚀 Cargando Dataset Maestro Multi-Temporada FPL (9 Temporadas, 224,143 filas)...")
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM fpl_historical_multi_season", conn)
    conn.close()

    pos_map = {"GK": 1, "GKP": 1, "DEF": 2, "MID": 3, "FWD": 4}
    df["element_type"] = df["position"].map(pos_map).fillna(2).astype(int)

    price_col = "value" if "value" in df.columns else "now_cost"
    df["price"] = df[price_col] / 10.0 if df[price_col].max() > 20 else df[price_col]

    df["minutes"] = df["minutes"].fillna(0)
    df["total_points"] = df["total_points"].fillna(0)
    df["expected_goals"] = df.get("expected_goals", pd.Series(0, index=df.index)).fillna(0)
    df["expected_assists"] = df.get("expected_assists", pd.Series(0, index=df.index)).fillna(0)

    # Filtrar solo jugadores que sumaron minutos o estuvieron convocados
    clean_df = df[df["minutes"] > 0].copy()

    features = ["element_type", "price", "minutes", "expected_goals", "expected_assists"]
    for col in ["influence", "creativity", "threat", "ict_index", "bonus", "bps", "transfers_in", "transfers_out"]:
        if col in clean_df.columns:
            clean_df[col] = pd.to_numeric(clean_df[col], errors="coerce").fillna(0)
            features.append(col)

    target = "total_points"
    X = clean_df[features].fillna(0)
    y = clean_df[target].fillna(0)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.15, random_state=42, shuffle=True
    )

    print(f"📊 Dataset Mega v5 Multi-Temporada: Train={len(X_train):,}, Test={len(X_test):,}")
    print("🔥 Entrenando Supermodelo Ensamble v5 (HistGB + Random Forest + Ridge)...")

    hgb = HistGradientBoostingRegressor(max_iter=200, learning_rate=0.04, max_depth=7, random_state=42)
    rf = RandomForestRegressor(n_estimators=200, max_depth=10, random_state=42, n_jobs=-1)
    ridge = Ridge(alpha=10.0)

    model = VotingRegressor(estimators=[("hgb", hgb), ("rf", rf), ("ridge", ridge)])
    model.fit(X_train, y_train)

    preds = model.predict(X_test)
    mae = mean_absolute_error(y_test, preds)
    rmse = np.sqrt(mean_squared_error(y_test, preds))

    print(f"\n✅ Supermodelo v5 Multi-Temporada Entrenado:")
    print(f"   - MAE en Test:  {mae:.4f} pts")
    print(f"   - RMSE en Test: {rmse:.4f} pts")

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump({
        "model": model,
        "features": features,
        "metadata": {
            "version": "v5.0.0-multi-season",
            "seasons": "2016/17 a 2024/25 (9 temporadas)",
            "total_rows": len(clean_df),
            "mae": round(mae, 4),
            "rmse": round(rmse, 4),
            "created_at": datetime.now().isoformat()
        }
    }, MODEL_PATH)

    print(f"💾 Artefacto v5 guardado en: {MODEL_PATH}")


if __name__ == "__main__":
    train_v5_multi_season()
