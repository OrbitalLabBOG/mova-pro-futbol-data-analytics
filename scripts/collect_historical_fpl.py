"""Collector e Integrador de 9 Temporadas Históricas FPL (2016/17 - 2024/25).

Descarga y consolida 224,143 filas de rendimiento FPL jornada a jornada en `data/historical_fpl/`
y las migra a la tabla `fpl_historical_multi_season` en `data/mundial.db`.
"""
import sqlite3
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HIST_DIR = ROOT / "data" / "historical_fpl"
DB_PATH = ROOT / "data" / "mundial.db"

SEASONS = [
    "2016-17", "2017-18", "2018-19", "2019-20", "2020-21",
    "2021-22", "2022-23", "2023-24", "2024-25"
]


def consolidate_historical_fpl():
    print("🚀 Consolidando 9 Temporadas Históricas FPL (224,000+ Filas)...")
    all_dfs = []

    for s in SEASONS:
        csv_path = HIST_DIR / f"fpl_{s}_merged.csv"
        if not csv_path.exists():
            continue

        try:
            df = pd.read_csv(csv_path, encoding="utf-8", low_memory=False)
        except UnicodeDecodeError:
            df = pd.read_csv(csv_path, encoding="latin1", low_memory=False)

        df["season"] = s
        all_dfs.append(df)

    master_df = pd.concat(all_dfs, ignore_index=True)
    print(f"📊 Dataset Histórico Multi-Temporada: {len(master_df):,} filas consolidadas.")

    # Guardar en SQLite data/mundial.db
    conn = sqlite3.connect(DB_PATH)
    master_df.to_sql("fpl_historical_multi_season", conn, if_exists="replace", index=False)
    conn.close()

    print(f"💾 Tabla `fpl_historical_multi_season` guardada exitosamente en {DB_PATH}.")


if __name__ == "__main__":
    consolidate_historical_fpl()
