"""Ingesta CSV -> almacen canonico SQLite.

Idempotente por (season, gw, element). Escritura atomica. Una columna ausente
en una temporada queda NULL, nunca 0 (REQ-F-001).

Este es el UNICO modulo que escribe en el almacen.
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import pandas as pd

from mova_fpl.data.identity import player_key
from mova_fpl.data.schema import ALL_COLUMNS, DROPPED, KEY, RENAME, SEASONS
from mova_fpl.data.sources import RAW, fetch_season_csv
from mova_fpl.data.store import DEFAULT_DB, TABLE

NUMERIC_EXCLUDE = {"season", "name", "player_key", "position", "team", "kickoff_time"}


def load_season_csv(season: str, raw_dir: Path = RAW) -> pd.DataFrame:
    path = raw_dir / f"merged_gw_{season}.csv"
    if not path.exists():
        path = fetch_season_csv(season, raw_dir)

    df = pd.read_csv(path, encoding="utf-8", encoding_errors="replace", low_memory=False)
    df = df.rename(columns=RENAME)
    df["season"] = season

    for col in DROPPED:
        df = df.drop(columns=[col], errors="ignore")

    # identidad estable entre temporadas (element se reasigna cada anio)
    df["player_key"] = df["name"].map(player_key)

    # columnas ausentes en esta temporada -> NA explicito, jamas 0
    for col in ALL_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA

    extra = set(df.columns) - set(ALL_COLUMNS)
    if extra:
        raise ValueError(
            f"{season}: columnas no contempladas por el esquema {sorted(extra)}. "
            "Agregarlas a schema.OPTIONAL o a schema.DROPPED de forma explicita."
        )

    df = df[list(ALL_COLUMNS)]
    for col in df.columns:
        if col not in NUMERIC_EXCLUDE:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["gw", "element", "fixture"])
    for col in ("gw", "element", "fixture"):
        df[col] = df[col].astype(int)

    # Sin tope de 38: la temporada 2019-20 (COVID) llega a gw 47 en la
    # numeracion del origen y esas 6.004 filas son observaciones reales.
    df = df[df["gw"] >= 1]

    # Duplicados exactos: artefacto del origen (20 filas en 2025-26).
    exact = int(df.duplicated(keep="first").sum())
    df = df.drop_duplicates(keep="first")
    # Tras quitar identicos, la clave debe ser unica. Si no lo es, es un dato
    # que no entendemos: fallar en vez de escoger uno en silencio.
    residual = df.duplicated(subset=list(KEY), keep=False)
    if residual.any():
        raise ValueError(
            f"{season}: {int(residual.sum())} filas con clave {KEY} repetida y "
            f"contenido distinto. Revisar antes de ingerir."
        )
    if exact:
        print(f"      ({season}: {exact} filas duplicadas exactas descartadas)")
    return df


def build(seasons: list[str], db_path: Path = DEFAULT_DB, raw_dir: Path = RAW) -> dict:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_suffix(".db.tmp")
    if tmp.exists():
        tmp.unlink()

    report = {}
    con = sqlite3.connect(tmp)
    try:
        first = True
        for season in seasons:
            df = load_season_csv(season, raw_dir)
            df.to_sql(TABLE, con, if_exists="replace" if first else "append", index=False)
            first = False
            report[season] = len(df)
            print(f"  {season}: {len(df):>6,} filas")
        key_cols = ", ".join(f'"{c}"' for c in KEY)
        con.execute(f"CREATE UNIQUE INDEX idx_pk ON {TABLE} ({key_cols})")
        con.execute(f'CREATE INDEX idx_season_gw ON {TABLE} ("season", "gw")')
        con.commit()
    finally:
        con.close()

    tmp.replace(db_path)                                # atomico
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingesta del almacen canonico FPL")
    ap.add_argument("--all", action="store_true", help="las 10 temporadas")
    ap.add_argument("--season", action="append", help="temporada puntual, repetible")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    args = ap.parse_args()

    seasons = SEASONS if args.all or not args.season else args.season
    print(f"Ingesta de {len(seasons)} temporadas -> {args.db}")
    report = build(seasons, Path(args.db))
    total = sum(report.values())
    print(f"\nTotal: {total:,} filas en {len(report)} temporadas")


if __name__ == "__main__":
    main()
