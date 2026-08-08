"""CLI: backtest walk-forward ciego sobre una temporada."""
from __future__ import annotations

import argparse

from mova_fpl.engine.runner import Config
from mova_fpl.engine.simulator import replay


def main() -> None:
    ap = argparse.ArgumentParser(description="Backtest walk-forward FPL")
    ap.add_argument("--season", default="2025-26")
    ap.add_argument("--mode", default="anonymized", choices=["named", "anonymized"])
    ap.add_argument("--policy", default="greedy-stub")
    ap.add_argument("--projector", default="naive", choices=["naive", "minutes"])
    ap.add_argument("--horizon", type=int, default=1)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max-gw", type=int, default=38)
    ap.add_argument("--run-id", help="reutilizar para reanudar una corrida cortada")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--out", help="escribir el reporte en Markdown")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    cfg = Config(policy=args.policy, projector=args.projector, horizon=args.horizon, seed=args.seed)
    print(f"Backtest {args.season} · politica {args.policy} · proyector {args.projector} · modo {args.mode} · semilla {args.seed}\n")
    report = replay(args.season, args.mode, cfg, run_id=args.run_id, resume=args.resume,
                    max_gw=args.max_gw, verbose=not args.quiet)

    print(f"\n{'=' * 66}")
    print(f"  MOTOR ({args.policy}): {report.total:,} pts en {len(report.gameweeks)} jornadas")
    for k, v in report.baselines.items():
        print(f"  {k:>10}: {v:,} pts   ({report.total - v:+,} vs motor)")
    techo = report.baselines.get("ceiling", 0)
    if techo:
        print(f"  captura del techo: {100 * report.total / techo:.1f}%")
    print(f"{'=' * 66}")
    print(f"  run_id: {report.run_id}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(report.render() + "\n")
        print(f"  reporte: {args.out}")


if __name__ == "__main__":
    main()
