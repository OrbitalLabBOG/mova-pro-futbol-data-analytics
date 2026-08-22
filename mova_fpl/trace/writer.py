"""Escritura de la traza. Por gameweek, para poder reanudar una corrida cortada."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from mova_fpl.trace.schema import DDL

DEFAULT_TRACE = Path(os.environ.get(
    "MOVA_TRACE_DB",
    Path(__file__).resolve().parents[2] / "data" / "processed" / "trace.db",
))


def git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=5,
                              cwd=Path(__file__).resolve().parents[2]).stdout.strip() or "unknown"
    except Exception:                                   # noqa: BLE001
        return "unknown"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TraceWriter:
    def __init__(self, db_path: Path | str = DEFAULT_TRACE):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._con() as con:
            for stmt in DDL:
                con.execute(stmt)

    def _con(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def start_run(self, run_id: str, season: str, mode: str, policy: str,
                  horizon: int, seed: int, config: dict) -> str:
        with self._con() as con:
            con.execute(
                "INSERT OR REPLACE INTO agent_runs (run_id, started_at, season, mode, policy,"
                " horizon, seed, git_sha, config_json, status) VALUES (?,?,?,?,?,?,?,?,?,'running')",
                (run_id, _now(), season, mode, policy, horizon, seed, git_sha(), json.dumps(config)),
            )
        return run_id

    def record_gw(self, run_id: str, decision, outcome=None, train_rows: int = 0,
                  state: str = "projected") -> None:
        j = lambda xs: json.dumps(list(xs))             # noqa: E731
        with self._con() as con:
            con.execute(
                """INSERT OR REPLACE INTO gw_decisions
                   (run_id, gw, state, fingerprint, squad_15, starters, captain, vice_captain,
                    bench_order, transfers_in, transfers_out, hits, chip, expected_points,
                    total_cost, actual_points, captain_points, auto_subs, train_rows, notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (run_id, decision.gw, state, decision.fingerprint(), j(decision.squad_15),
                 j(decision.starters), decision.captain, decision.vice_captain,
                 j(decision.bench_order), j(decision.transfers_in), j(decision.transfers_out),
                 decision.hits, decision.chip, decision.expected_points, decision.total_cost,
                 outcome.points if outcome else None,
                 outcome.captain_points if outcome else None,
                 json.dumps([list(s) for s in outcome.auto_subs]) if outcome else None,
                 train_rows, json.dumps(list(decision.notes))),
            )

    def record_baselines(self, run_id: str, gw: int, valores: dict) -> None:
        with self._con() as con:
            con.executemany(
                "INSERT OR REPLACE INTO benchmarks (run_id, gw, baseline, points) VALUES (?,?,?,?)",
                [(run_id, gw, k, int(v)) for k, v in valores.items()],
            )

    def finish_run(self, run_id: str, total_points: int, status: str = "completed") -> None:
        with self._con() as con:
            con.execute("UPDATE agent_runs SET finished_at=?, total_points=?, status=? WHERE run_id=?",
                        (_now(), int(total_points), status, run_id))

    def completed_gws(self, run_id: str) -> set[int]:
        with self._con() as con:
            rows = con.execute(
                "SELECT gw FROM gw_decisions WHERE run_id=? AND actual_points IS NOT NULL", (run_id,)
            ).fetchall()
        return {r[0] for r in rows}

    # ------------------------------------------------------------- bitacora

    def record_intervention(self, run_id: str, gw: int, intervention, attribution=None,
                            seq: int = 0) -> None:
        """Anota una intervencion con lo que prometia. El resultado se liquida despues."""
        with self._con() as con:
            con.execute(
                "INSERT OR REPLACE INTO interventions (run_id, gw, seq, author, rationale,"
                " payload, changed, expected_delta, realized_delta, points_with,"
                " points_without, detail, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, gw, seq, intervention.author, intervention.rationale,
                 json.dumps(intervention.to_dict()),
                 int(bool(attribution.changed)) if attribution else None,
                 attribution.expected_delta if attribution else None,
                 attribution.realized_delta if attribution else None,
                 attribution.points_with if attribution else None,
                 attribution.points_without if attribution else None,
                 json.dumps(attribution.detail) if attribution else None,
                 _now()))

    def settle_intervention(self, run_id: str, gw: int, points_with: int,
                            points_without: int, seq: int = 0) -> None:
        """Cierra la ficha con puntos reales, una vez jugada la jornada."""
        with self._con() as con:
            con.execute(
                "UPDATE interventions SET points_with = ?, points_without = ?,"
                " realized_delta = ? WHERE run_id = ? AND gw = ? AND seq = ?",
                (points_with, points_without, points_with - points_without, run_id, gw, seq))
