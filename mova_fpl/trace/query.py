"""Consultas sobre la traza. Responder sin recomputar es el punto (REQ-F-010)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from mova_fpl.trace.writer import DEFAULT_TRACE


def _con(db: Path | str = DEFAULT_TRACE) -> sqlite3.Connection:
    return sqlite3.connect(Path(db))


def runs(db=DEFAULT_TRACE) -> pd.DataFrame:
    with _con(db) as con:
        return pd.read_sql_query("SELECT * FROM agent_runs ORDER BY started_at DESC", con)


def latest_run(db=DEFAULT_TRACE) -> str | None:
    r = runs(db)
    return None if r.empty else r.iloc[0]["run_id"]


def decisions(run_id: str, db=DEFAULT_TRACE) -> pd.DataFrame:
    with _con(db) as con:
        return pd.read_sql_query(
            "SELECT * FROM gw_decisions WHERE run_id=? ORDER BY gw", con, params=(run_id,))


def vs_baseline(run_id: str, baseline: str = "template", db=DEFAULT_TRACE) -> pd.DataFrame:
    """En que jornadas el motor difirio del baseline y quien gano.

    Es la pregunta que justifica tener traza.
    """
    with _con(db) as con:
        return pd.read_sql_query(
            """SELECT d.gw, d.actual_points AS motor, b.points AS baseline,
                      d.actual_points - b.points AS delta,
                      CASE WHEN d.actual_points > b.points THEN 'motor'
                           WHEN d.actual_points < b.points THEN 'baseline'
                           ELSE 'empate' END AS gana
               FROM gw_decisions d JOIN benchmarks b ON b.run_id=d.run_id AND b.gw=d.gw
               WHERE d.run_id=? AND b.baseline=? ORDER BY d.gw""",
            con, params=(run_id, baseline))


def summary(run_id: str, db=DEFAULT_TRACE) -> dict:
    d = decisions(run_id, db)
    with _con(db) as con:
        b = pd.read_sql_query(
            "SELECT baseline, SUM(points) AS total FROM benchmarks WHERE run_id=? GROUP BY baseline",
            con, params=(run_id,))
    return {
        "run_id": run_id,
        "gameweeks": len(d),
        "motor": int(d["actual_points"].sum()) if not d.empty else 0,
        "hits": int(d["hits"].sum()) if not d.empty else 0,
        "baselines": dict(zip(b["baseline"], b["total"].astype(int))) if not b.empty else {},
    }
