#!/usr/bin/env python3
"""Imprime el bracket completo lleno por el modelo (16vos → campeón).

Usa los mismos insumos que la simulación: FT real > en vivo > mercado h2h > modelo,
con ratings anclados al mercado. Uso: python scripts/bracket.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mova_data.db import get_db, init_db
from mova_data.teams import resolve
from mova_data.collectors.whoscored import WhoScoredCollector
from mova_data.config import RAW_DIR
from mova_model import match_model, strengths, simulate
from mova_model.market import p_market_winner


def main():
    init_db()
    params = match_model.load()
    with get_db() as conn:
        rid = conn.execute("SELECT run_id FROM model_runs WHERE started_at IS NOT NULL "
                           "ORDER BY started_at DESC LIMIT 1").fetchone()[0]
        eff = strengths.effective_ratings(conn, rid)
        decided = simulate.decided_matches(conn)
        market = simulate.market_advance(conn, rid)
        live = {}
        try:
            rows = WhoScoredCollector(RAW_DIR / "whoscored").fetch_live()
            live = simulate.live_advance_map(rows, eff, params, lambda n: resolve(conn, n))
        except Exception:
            pass
        anc, _ = simulate.anchor_to_market(conn, eff, params, p_market_winner(conn),
                                            w=0.65, decided=decided, live=live, market=market)
        rounds, champ = simulate.fill_bracket(anc, params, decided, live, market)

    print("=" * 60)
    print("  BRACKET DEL MODELO — Mundial 2026 (camino más probable)")
    print("=" * 60)
    for lab, res in rounds:
        print(f"\n── {lab} ──")
        for a, b, w, p in res:
            mark = "✔" if frozenset((a, b)) in decided else " "
            loser = b if w == a else a
            print(f"  {mark} {w:24} vence a {loser:22} ({p*100:.0f}%)")
    print("\n" + "=" * 60)
    print(f"  🏆 CAMPEÓN DEL MODELO: {champ}")
    print("=" * 60)
    print("  ✔ = resultado real ya jugado · resto = predicción del modelo")


if __name__ == "__main__":
    main()
