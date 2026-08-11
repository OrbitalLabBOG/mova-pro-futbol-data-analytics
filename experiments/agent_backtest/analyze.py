"""Analisis de una corrida del backtest con agencia: atribucion, memoria, costos."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def main(run_id: str, baseline_id: str | None = None) -> None:
    con = sqlite3.connect(ROOT / "data/processed/trace.db")
    con.row_factory = sqlite3.Row

    print(f"=== corrida {run_id} ===")
    total = con.execute("SELECT total_points, status FROM agent_runs WHERE run_id=?",
                        (run_id,)).fetchone()
    print(f"total: {total['total_points']} pts ({total['status']})")
    if baseline_id:
        b = con.execute("SELECT total_points FROM agent_runs WHERE run_id=?",
                        (baseline_id,)).fetchone()
        print(f"baseline: {b['total_points']} pts  →  delta del agente: "
              f"{total['total_points'] - b['total_points']:+d} pts")

    print("\n--- intervenciones (expected vs realized) ---")
    filas = list(con.execute(
        "SELECT gw, changed, expected_delta, realized_delta, points_with, points_without,"
        " rationale FROM interventions WHERE run_id=? ORDER BY gw", (run_id,)))
    esp = rea = con_efecto = 0
    for f in filas:
        marca = "≠" if f["changed"] else "="
        print(f"GW{f['gw']:>2} {marca} esperaba {f['expected_delta']:+6.2f} xp | "
              f"real {f['realized_delta']:+3d} pts ({f['points_with']} vs {f['points_without']}) | "
              f"{(f['rationale'] or '')[:80]}")
        if f["changed"]:
            con_efecto += 1
            esp += f["expected_delta"] or 0
            rea += f["realized_delta"] or 0
    print(f"\n{len(filas)} intervenciones, {con_efecto} cambiaron la decision")
    print(f"prometido: {esp:+.1f} xp | entregado: {rea:+d} pts | calibracion (brecha): {esp - rea:+.1f}")

    mem_path = ROOT / "outputs/agent_backtest" / run_id / "memoria.json"
    if mem_path.exists():
        m = json.loads(mem_path.read_text())
        print(f"\n--- memoria: {len(m['reglas'])} reglas, {len(m['reflexiones'])} reflexiones ---")
        for r in m["reglas"]:
            print(f"[{r['confianza']} GW{r['nacida_gw']}] {r['regla'][:120]}")

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
