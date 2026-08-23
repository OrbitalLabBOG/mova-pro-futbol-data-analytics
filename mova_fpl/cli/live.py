"""CLI: decision en vivo para una jornada de la temporada en curso (WP-007).

Ciclo completo: leer el estado publico -> proyectar -> optimizar -> emitir acta.
Cierra el objetivo primario de la iniciativa.

Esta CLI **no escribe en FPL** y no puede hacerlo: la unica primitiva de red del
paquete es un GET (REQ-S-002, verificado por tests/test_readonly_http.py). El
acta se entrega y una persona la introduce.
"""
from __future__ import annotations

import argparse
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from mova_fpl.data import live
from mova_fpl.data.store import Store
from mova_fpl.engine.planner import PlannerConfig, plan
from mova_fpl.engine.policies import optimizer_config
from mova_fpl.engine.projection import points_projection
from mova_fpl.engine.report import render
from mova_fpl.engine.runner import Config, decide
from mova_fpl.engine.simulator import _candidates
from mova_fpl.engine.state import State
from dataclasses import replace
from mova_fpl.models.registry import git_sha, load
from mova_fpl.optimizer.horizon import build_xp_matrix
from mova_fpl.rules import get as get_rules
from mova_fpl.trace import TraceWriter

ROOT = Path(__file__).resolve().parents[2]


def _dias(deadline: str | None, ahora: datetime) -> float | None:
    if not deadline:
        return None
    try:
        cierre = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (cierre - ahora).total_seconds() / 86400.0

#: temporada de la que se aprende para decidir en la siguiente
HISTORICO_HASTA = "2025-26"


def _fuente(team_id, snapshot_dir: str | None = None,
            private_team_state: str | None = None) -> str:
    base = "fantasy.premierleague.com/api (bootstrap-static + fixtures)"
    if snapshot_dir:
        base += f" · snapshot {snapshot_dir}"
    if team_id:
        base += " + estado publico del equipo"
    if private_team_state:
        base += " + estado autenticado sanitizado"
    return base + ", solo GET"


def _estado_equipo(args, boot, roster, rules) -> dict:
    """Plantilla, banco, libres y chips reales. Sin `--team-id`, arranque en frio."""
    team_id = args.team_id or os.environ.get("FPL_TEAM_ID")
    if not team_id:
        if args.chips:
            print("      ⚠️  sin --team-id no se sabe que chips quedan: se asumen los ocho")
        return {"squad": None, "bank": 0.0, "free_transfers": 1,
                "chips_used": (), "en_blanco": [], "ultima_gw": None}

    if args.private_team_state:
        from mova_fpl.data.private_state import load as load_private

        payload, _ = load_private(Path(args.private_team_state), expected_team_id=int(team_id))
        estado = live.private_team_state(payload, int(team_id), args.gw, roster, rules, boot)
    else:
        estado = live.team_state(int(team_id), args.gw, roster, rules, boot)
    if estado["squad"] is None:
        print(f"      equipo {team_id}: sin jornadas jugadas todavia (arranque en frio)")
        return estado
    gastados = ", ".join(f"{u.chip}@GW{u.gw}" for u in estado["chips_used"]) or "ninguno"
    source = "API autenticada" if estado.get("source") == "authenticated_api" else "API pública"
    print(f"      equipo {team_id}: plantilla de la GW{estado['ultima_gw']} ({source}) · "
          f"banco £{estado['bank']:.1f}M · {estado['free_transfers']} libres")
    print(f"      chips gastados: {gastados}")
    if estado["en_blanco"]:
        print(f"      {len(estado['en_blanco'])} jugadores en jornada en blanco")
    return estado


def main() -> None:
    ap = argparse.ArgumentParser(description="Decision en vivo de una gameweek FPL")
    ap.add_argument("--season", default="2026-27")
    ap.add_argument("--gw", type=int, required=True)
    ap.add_argument("--policy", default="milp")
    ap.add_argument("--horizon", type=int, default=3)
    ap.add_argument("--top-k", type=int, default=0, help="0 = sin recorte de mercado")
    ap.add_argument("--version", default="1.0.0")
    ap.add_argument("--minutes-version", default="1.0.0")
    ap.add_argument(
        "--snapshot-dir",
        help="directorio inmutable creado por mova_fpl.cli.collect_live; evita drift de API",
    )
    ap.add_argument("--team-id", type=int, default=None,
                    help="numero del equipo (el de la URL /entry/<ID>/). "
                         "Sin el, la decision se toma desde cero. "
                         "Tambien se lee de la variable FPL_TEAM_ID")
    ap.add_argument(
        "--private-team-state",
        help="directorio de snapshot autenticado sanitizado; prevalece sobre reconstrucción pública",
    )
    ap.add_argument("--chips", action="store_true",
                    help="deja que el planificador proponga chips (exige --team-id)")
    ap.add_argument("--lookahead", type=int, default=6,
                    help="jornadas de calendario que el planificador considera anunciadas")
    ap.add_argument("--dry-run", action="store_true",
                    help="no persiste la decision en la traza")
    ap.add_argument("--out", help="ruta del acta; por defecto outputs/fpl/{season}/gwNN_decision.md")
    args = ap.parse_args()

    t0 = time.time()
    emitida = datetime.now(timezone.utc)

    print(f"[1/5] Leyendo estado publico de FPL (solo GET)...")
    if args.snapshot_dir:
        from mova_fpl.cli.collect_live import load_snapshot
        boot, fx, _ = load_snapshot(Path(args.snapshot_dir))
    else:
        boot, fx = live.bootstrap(), live.fixtures()
    tope = args.gw + max(1, args.horizon) - 1
    roster = live.roster(boot, fx, args.season, args.gw)
    calendario = live.team_schedule(fx, boot, args.gw, tope)
    equipos = live.teams(boot)
    limite = live.deadline(boot, args.gw)
    print(f"      {len(roster)} jugadores · {roster['team'].nunique()} clubes · "
          f"deadline {limite}")
    lesionados = int((roster["disponibilidad"] < 1.0).sum())
    print(f"      {lesionados} con el parte medico tocado (lesion, duda, sancion)")

    print(f"[2/5] Cargando historico hasta {HISTORICO_HASTA} y modelos...")
    store = Store()
    # Solo la ultima temporada cerrada, no las diez. Es lo mismo que ve el
    # proyector en el backtest —donde `as_of` acota a la temporada en curso— y
    # asi la decision en vivo se comporta como la que se midio. Las diez
    # temporadas si entran, pero en el AJUSTE del modelo, no en el estado.
    historia = store.as_of(HISTORICO_HASTA, 39)
    modelos = {"minutes": load("minutes", args.minutes_version),
               "points": load("points", args.version)}
    temporadas_modelo = sorted(set(modelos["minutes"].metadata.get("temporadas", ()))
                               | set(modelos["points"].metadata.get("temporadas", ())))
    print(f"      {len(historia):,} filas de {HISTORICO_HASTA} · "
          f"modelos ajustados con {len(temporadas_modelo)} temporadas")

    print(f"[3/5] Proyectando xP por componentes...")
    xp, desglose = points_projection(historia, roster, modelos, args.season,
                                     con_desglose=True, equipos=equipos,
                                     disponibilidad=roster["disponibilidad"].to_numpy())
    candidatos = _candidates(roster, xp)
    print(f"      {len(candidatos)} candidatos · xP maximo {float(xp.max()):.2f}")

    print(f"[4/5] Optimizando (politica {args.policy}, horizonte {args.horizon})...")
    rules_mod = get_rules(args.season)
    matriz = build_xp_matrix(candidatos, calendario, args.gw, tope - args.gw + 1)
    cfg = Config(policy=args.policy, projector="points", model_version=args.version,
                 horizon=args.horizon, top_k=args.top_k, time_limit=600,
                 chip_policy="planner" if args.chips else "none",
                 structure_lookahead=args.lookahead)

    equipo = _estado_equipo(args, boot, roster, rules_mod.SQUAD)
    estado = State(season=args.season, gw=args.gw, candidates=candidatos,
                   squad=equipo["squad"], free_transfers=equipo["free_transfers"],
                   bank=equipo["bank"], rules=rules_mod.SQUAD, horizon_xp=matriz,
                   chips=rules_mod.CHIPS if args.chips else None,
                   chips_used=equipo["chips_used"],
                   schedule=live.team_schedule(fx, boot, args.gw,
                                               args.gw + args.lookahead) if args.chips else {})

    veredicto = None
    if args.chips:
        pcfg = PlannerConfig(enabled=True, structure_lookahead=args.lookahead)
        veredicto = plan(estado, matriz, optimizer_config(cfg, len(matriz)), pcfg)
        print(f"      {veredicto.as_note()}")
        if veredicto.chip:
            estado = replace(estado, chips_allowed={args.gw: frozenset({veredicto.chip})})

    decision = decide(args.gw, estado, cfg)

    print(f"[5/5] Componiendo el acta...")
    det = desglose.set_index("element", drop=False)
    acta = render(decision, roster, det.loc[list(decision.squad_15)].reset_index(drop=True), {
        "season": args.season, "emitida": emitida.isoformat(timespec="seconds"),
        "deadline": limite, "policy": args.policy, "horizon": args.horizon,
        "v_minutes": args.minutes_version, "v_points": args.version, "git_sha": git_sha(),
        "rules": rules_mod.SQUAD, "dias_al_deadline": _dias(limite, emitida),
        "fuente": _fuente(args.team_id, args.snapshot_dir, args.private_team_state),
        "chip_verdict": veredicto, "chips_used": equipo["chips_used"],
        "catalogo_chips": rules_mod.CHIPS if args.chips else None,
        "equipo": equipo,
    })

    destino = Path(args.out) if args.out else (
        ROOT / "outputs" / "fpl" / args.season / f"gw{args.gw:02d}_decision.md")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(acta.texto, encoding="utf-8")

    if not args.dry_run:
        run_id = f"{args.season}-live-{args.policy}-h{args.horizon}"
        trace = TraceWriter()
        trace.start_run(run_id, args.season, "named", args.policy, args.horizon, 0,
                        {"live": True, "deadline": limite, "git_sha": git_sha()})
        trace.record_gw(run_id, decision, None, train_rows=len(historia), state="committed")
        print(f"      traza: {run_id} en estado committed")

    seg = time.time() - t0
    print(f"\n{'=' * 68}")
    print(f"  ACTA {args.season} GW{args.gw} · {'VALIDA' if acta.valida else 'INVALIDA'}")
    print(f"  xP del once (con capitan): {decision.expected_points:.1f}")
    if decision.chip:
        print(f"  CHIP: {decision.chip}")
    print(f"  coste £{acta.total:.1f}M · banco £{acta.banco:.1f}M")
    if not acta.valida:
        for v in acta.violaciones:
            print(f"    !! {v.code}: {v.detail}")
    print(f"  ciclo completo: {seg:.1f} s")
    print(f"{'=' * 68}")
    try:
        print(f"  {destino.relative_to(ROOT)}")
    except ValueError:                    # --out fuera del repo: se imprime entera
        print(f"  {destino}")


if __name__ == "__main__":
    main()
