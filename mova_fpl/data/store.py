"""Almacen canonico. UNICA via de lectura de datos historicos.

ADR-002: el leakage temporal deja de ser expresable. Toda lectura pasa por
`as_of(season, gw)`, que devuelve exclusivamente filas con gw' < gw, y el
resultado se verifica ANTES de entregarse. La verificacion corre siempre, no
solo bajo pytest: si el SQL se edita mal, la corrida falla.

No agregar aqui ningun metodo publico que devuelva filas sin ventana temporal.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from mova_fpl.data.schema import ALL_COLUMNS, FORBIDDEN_AS_FEATURE, SEASONS

DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "processed" / "fpl_canonical.db"
TABLE = "player_gameweek"


class LeakageError(RuntimeError):
    """Se detecto una observacion fuera de la ventana temporal declarada."""


def assert_causal(df: pd.DataFrame, season: str, gw: int) -> None:
    """Falla si `df` contiene observaciones que no existian antes de `gw`.

    Es la red de seguridad de ADR-002: se aplica al RESULTADO, de modo que no
    depende de que la consulta SQL este bien escrita.
    """
    if df.empty:
        return
    if "gw" not in df.columns:
        raise LeakageError(
            f"frame sin columna 'gw': imposible verificar causalidad para {season} gw={gw}"
        )
    max_gw = int(df["gw"].max())
    if max_gw >= gw:
        offending = sorted(df.loc[df["gw"] >= gw, "gw"].unique().tolist())
        raise LeakageError(
            f"LEAKAGE en {season}: se pidio as_of(gw={gw}) pero el frame trae "
            f"gameweeks {offending} (max={max_gw}). Filas afectadas: "
            f"{int((df['gw'] >= gw).sum())}."
        )
    if "season" in df.columns:
        bad = set(df["season"].unique()) - {season}
        if bad:
            raise LeakageError(f"mezcla de temporadas en as_of({season}): {sorted(bad)}")


def feature_columns(columns) -> list[str]:
    """Filtra las columnas que son resultado, no insumo (leakage de target)."""
    return [c for c in columns if c not in FORBIDDEN_AS_FEATURE]


class Store:
    """Acceso de solo lectura al almacen canonico, con ventana temporal obligatoria."""

    def __init__(self, db_path: Path | str = DEFAULT_DB):
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(
                f"no existe {self.db_path}. Correr: python -m mova_fpl.data.ingest --all"
            )

    def _connect(self) -> sqlite3.Connection:
        # solo lectura: cualquier escritura pertenece a ingest.py
        return sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)

    # ---------------------------------------------------------------- lectura

    def as_of(self, season: str, gw: int, columns: list[str] | None = None) -> pd.DataFrame:
        """Observaciones de `season` estrictamente anteriores a `gw`.

        gw=1 devuelve vacio por construccion: es el cold start real.
        """
        if season not in SEASONS:
            raise ValueError(f"temporada desconocida: {season}. Validas: {SEASONS}")
        if not isinstance(gw, (int,)) or isinstance(gw, bool) or gw < 1:
            raise ValueError(f"gw debe ser entero >= 1, recibido {gw!r}")

        cols = self._resolve_columns(columns)
        sql = f"SELECT {', '.join(cols)} FROM {TABLE} WHERE season = ? AND gw < ? ORDER BY gw, element"
        with self._connect() as con:
            df = pd.read_sql_query(sql, con, params=(season, int(gw)))

        assert_causal(df, season, gw)          # red de seguridad, siempre activa
        return df

    def season_upto(self, season: str, gw: int, columns=None) -> pd.DataFrame:
        """Alias explicito de as_of, para llamadas donde 'upto' se lee mejor."""
        return self.as_of(season, gw, columns)

    def multi_season_as_of(self, season: str, gw: int, columns=None) -> pd.DataFrame:
        """Historico completo de temporadas ANTERIORES + lo transcurrido de `season`.

        Es lo que necesita un modelo que entrena con 9 temporadas cerradas mas
        las jornadas ya jugadas de la actual.
        """
        idx = SEASONS.index(season)
        past = SEASONS[:idx]
        cols = self._resolve_columns(columns)
        frames = []
        if past:
            ph = ",".join("?" * len(past))
            sql = f"SELECT {', '.join(cols)} FROM {TABLE} WHERE season IN ({ph}) ORDER BY season, gw, element"
            with self._connect() as con:
                frames.append(pd.read_sql_query(sql, con, params=past))
        current = self.as_of(season, gw, columns)
        if not current.empty:
            frames.append(current)
        frames = [f for f in frames if not f.empty]
        if not frames:
            return pd.DataFrame(columns=cols)
        out = frames[0] if len(frames) == 1 else pd.concat(frames, ignore_index=True)
        # la ventana de la temporada objetivo ya fue verificada por as_of
        assert_causal(out[out["season"] == season], season, gw)
        return out

    def fixtures(self, season: str, gw_from: int, gw_to: int) -> pd.DataFrame:
        """Calendario. NO contiene resultados: es informacion conocida antes de jugar."""
        sql = (
            f"SELECT DISTINCT season, gw, fixture, opponent_team, was_home, kickoff_time "
            f"FROM {TABLE} WHERE season = ? AND gw BETWEEN ? AND ? ORDER BY gw, fixture"
        )
        with self._connect() as con:
            return pd.read_sql_query(sql, con, params=(season, int(gw_from), int(gw_to)))

    # ------------------------------------------------------------- metadatos

    def coverage(self) -> pd.DataFrame:
        """Matriz temporada x columna con conteo de valores no nulos."""
        with self._connect() as con:
            counts = pd.read_sql_query(
                f"SELECT season, COUNT(*) AS filas FROM {TABLE} GROUP BY season ORDER BY season", con
            )
            rows = []
            for season in counts["season"]:
                agg = ", ".join(f'SUM(CASE WHEN "{c}" IS NOT NULL THEN 1 ELSE 0 END) AS "{c}"'
                                for c in ALL_COLUMNS if c != "season")
                r = pd.read_sql_query(
                    f"SELECT {agg} FROM {TABLE} WHERE season = ?", con, params=(season,)
                ).iloc[0]
                r["season"] = season
                rows.append(r)
        out = pd.DataFrame(rows).set_index("season")
        return out.merge(counts.set_index("season"), left_index=True, right_index=True)

    def seasons(self) -> list[str]:
        with self._connect() as con:
            return pd.read_sql_query(
                f"SELECT DISTINCT season FROM {TABLE} ORDER BY season", con
            )["season"].tolist()

    def row_count(self) -> int:
        with self._connect() as con:
            return int(pd.read_sql_query(f"SELECT COUNT(*) AS n FROM {TABLE}", con)["n"].iloc[0])

    # --------------------------------------------------------------- interno

    def _resolve_columns(self, columns: list[str] | None) -> list[str]:
        if columns is None:
            return list(ALL_COLUMNS)
        unknown = set(columns) - set(ALL_COLUMNS)
        if unknown:
            raise ValueError(f"columnas desconocidas: {sorted(unknown)}")
        cols = list(columns)
        for required in ("gw", "season"):          # necesarias para verificar causalidad
            if required not in cols:
                cols.append(required)
        return cols
