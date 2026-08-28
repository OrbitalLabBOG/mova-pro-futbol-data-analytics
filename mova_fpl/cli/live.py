"""CLI: decision en vivo para una jornada de la temporada en curso (WP-007).

Ciclo completo: leer el estado publico -> proyectar -> optimizar -> emitir acta.
Cierra el objetivo primario de la iniciativa.

Esta CLI **no escribe en FPL** y no puede hacerlo: la unica primitiva de red del
paquete es un GET (REQ-S-002, verificado por tests/test_readonly_http.py). El
acta se entrega y una persona la introduce.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from dataclasses import replace
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
                "chips_used": (), "en_blanco": [], "ultima_gw": None,
                "current_picks": ()}

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


def _do_nothing_decision(state: State, picks: tuple[dict, ...]):
    """Representa literalmente el estado previo; no optimiza ni cambia C/V."""
    from mova_fpl.engine.state import Decision

    if state.squad is None or not picks:
        return None
    ordered = sorted(picks, key=lambda item: int(item.get("position", 0)))
    starters = tuple(int(item["element"]) for item in ordered if int(item["position"]) <= 11)
    bench = tuple(int(item["element"]) for item in ordered if int(item["position"]) > 11)
    captain = next((int(item["element"]) for item in ordered if item.get("is_captain")), None)
    vice = next((int(item["element"]) for item in ordered if item.get("is_vice_captain")), None)
    if len(starters) != 11 or len(bench) != 4 or captain is None or vice is None:
        return None
    xp = (state.horizon_xp or {}).get(
        state.gw, {candidate.element: candidate.xp for candidate in state.candidates}
    )
    expected = sum(float(xp.get(element, 0.0)) for element in starters)
    expected += float(xp.get(captain, 0.0))
    return Decision(
        season=state.season, gw=state.gw,
        squad_15=tuple(int(item["element"]) for item in ordered),
        starters=starters, captain=captain, vice_captain=vice,
        bench_order=bench, expected_points=round(expected, 2),
        total_cost=round(sum(player.price for player in state.squad.players), 1),
        bank_after=round(state.bank, 1), policy="do_nothing",
        notes=("estado exacto observado; cero cambios",),
    )


def _engine_violations(decision, state: State) -> list[dict]:
    """Aplica las reglas puras a cada candidato antes de entregarlo al harness."""
    from mova_fpl.rules.base import Squad, SquadPlayer
    from mova_fpl.rules.market import selling_price, squad_value
    from mova_fpl.rules.squad import validate_squad

    by_id = state.by_id()
    owned = {player.element: player for player in (state.squad.players if state.squad else ())}
    players = []
    for element in decision.squad_15:
        candidate = by_id.get(element)
        previous = owned.get(element)
        if candidate is None and previous is None:
            return [{"code": "UNKNOWN_PLAYER", "detail": f"element {element}"}]
        players.append(SquadPlayer(
            element=element,
            position=candidate.position if candidate else previous.position,
            team=candidate.team if candidate else previous.team,
            price=candidate.price if candidate else previous.price,
            purchase_price=previous.purchase_price if previous else None,
        ))
    squad = Squad(
        players=tuple(players), starters=decision.starters, captain=decision.captain,
        vice_captain=decision.vice_captain, bench_order=decision.bench_order,
        bank=decision.bank_after,
    )
    result = [
        {"code": item.code, "detail": item.detail}
        # El valor de mercado de una plantilla adquirida puede superar las 100M
        # por apreciacion. La asequibilidad se concilia abajo con precios de venta,
        # compras y banco, en vez de comparar precios actuales con el presupuesto
        # inicial.
        for item in validate_squad(squad, state.rules, check_budget=False)
    ]

    selected = set(decision.squad_15)
    previous_ids = set(owned)
    actual_in = selected - previous_ids
    actual_out = previous_ids - selected

    if decision.chip != "free_hit":
        declared_in = set(decision.transfers_in)
        declared_out = set(decision.transfers_out)
        if declared_in != actual_in or declared_out != actual_out:
            result.append({
                "code": "TRANSFER_DIFF",
                "detail": (
                    f"declarado in={sorted(declared_in)} out={sorted(declared_out)}; "
                    f"real in={sorted(actual_in)} out={sorted(actual_out)}"
                ),
            })

    selected_cost = round(sum(player.price for player in players), 1)
    if state.squad is None:
        expected_bank = round(float(state.rules["budget"]) - selected_cost, 1)
    elif decision.chip == "free_hit":
        available = squad_value(state.squad.players, use_selling_price=True) + state.bank
        expected_bank = round(available - selected_cost, 1)
    else:
        sale_proceeds = sum(
            selling_price(owned[element].purchase_price, owned[element].price)
            if owned[element].purchase_price is not None else owned[element].price
            for element in actual_out
        )
        purchase_cost = sum(by_id[element].price for element in actual_in if element in by_id)
        expected_bank = round(state.bank + sale_proceeds - purchase_cost, 1)

    if expected_bank < -1e-9 or decision.bank_after < -1e-9:
        result.append({
            "code": "BUDGET",
            "detail": (
                f"banco conciliado {expected_bank:.1f}M; "
                f"decision declara {decision.bank_after:.1f}M"
            ),
        })
    elif abs(expected_bank - decision.bank_after) > 0.05:
        result.append({
            "code": "BANK_RECONCILIATION",
            "detail": (
                f"banco conciliado {expected_bank:.1f}M != "
                f"declarado {decision.bank_after:.1f}M"
            ),
        })
    return result


def _candidate(key: str, label: str, decision, state: State) -> dict:
    return {
        "candidate_key": key,
        "label": label,
        "decision": decision.to_dict(),
        "violations": _engine_violations(decision, state),
    }


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
    ap.add_argument(
        "--json-out",
        help="bundle máquina de baseline, do_nothing y alternativa; no reemplaza el acta",
    )
    ap.add_argument(
        "--as-of",
        help="timestamp UTC sellado para replay; por defecto usa el reloj actual",
    )
    args = ap.parse_args()

    t0 = time.time()
    emitida = (
        datetime.fromisoformat(args.as_of.replace("Z", "+00:00")).astimezone(timezone.utc)
        if args.as_of else datetime.now(timezone.utc)
    )

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
    base_state = State(
        season=args.season, gw=args.gw, candidates=candidatos,
        squad=equipo["squad"], free_transfers=equipo["free_transfers"],
        bank=equipo["bank"], rules=rules_mod.SQUAD, horizon_xp=matriz,
        chips=rules_mod.CHIPS if args.chips else None,
        chips_used=equipo["chips_used"],
        schedule=live.team_schedule(fx, boot, args.gw,
                                    args.gw + args.lookahead) if args.chips else {},
    )
    estado = base_state

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
    from mova_fpl.data.snapshot import event_context
    acta = render(decision, roster, det.loc[list(decision.squad_15)].reset_index(drop=True), {
        "season": args.season, "emitida": emitida.isoformat(timespec="seconds"),
        "deadline": limite, "policy": args.policy, "horizon": args.horizon,
        "v_minutes": args.minutes_version, "v_points": args.version, "git_sha": git_sha(),
        "rules": rules_mod.SQUAD, "dias_al_deadline": _dias(limite, emitida),
        "fuente": _fuente(args.team_id, args.snapshot_dir, args.private_team_state),
        "chip_verdict": veredicto, "chips_used": equipo["chips_used"],
        "catalogo_chips": rules_mod.CHIPS if args.chips else None,
        "equipo": equipo,
        "event_context": event_context(boot, fx, args.gw),
    })

    destino = Path(args.out) if args.out else (
        ROOT / "outputs" / "fpl" / args.season / f"gw{args.gw:02d}_decision.md")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(acta.texto, encoding="utf-8")

    if args.json_out:
        no_chip_state = replace(base_state, chips_allowed={})
        no_chip = decide(args.gw, no_chip_state, cfg)
        owned = frozenset(
            player.element for player in (base_state.squad.players if base_state.squad else ())
        )
        hold = decide(
            args.gw,
            replace(no_chip_state, lock_in=owned),
            cfg,
        ) if owned else no_chip
        do_nothing = _do_nothing_decision(
            base_state, tuple(equipo.get("current_picks") or ())
        ) or hold
        alternative = no_chip if no_chip.fingerprint() != decision.fingerprint() else hold
        event = event_context(boot, fx, args.gw)
        report_sha = hashlib.sha256(destino.read_bytes()).hexdigest()
        payload = {
            "schema": "mova-live-decision-candidates-v1",
            "season": args.season,
            "gw": args.gw,
            "selected_candidate_key": "milp_baseline",
            "candidates": [
                _candidate("do_nothing", "Estado observado sin cambios", do_nothing, base_state),
                _candidate("milp_baseline", "MILP + planner vigente", decision, estado),
                _candidate(
                    "primary_alternative",
                    "MILP sin chip" if alternative is no_chip else "Conservar plantilla y optimizar XI",
                    alternative,
                    no_chip_state,
                ),
            ],
            "team_state": {
                "source": equipo.get("source"),
                "fingerprint": equipo.get("fingerprint"),
                "free_transfers": equipo.get("free_transfers"),
                "bank": equipo.get("bank"),
                "squad_size": len(equipo["squad"].players) if equipo.get("squad") else 0,
                "chips_available": list(equipo.get("chips_available") or ()),
            },
            "event_context": event,
            "engine": {
                "policy": args.policy,
                "horizon": args.horizon,
                "points_model_version": args.version,
                "minutes_model_version": args.minutes_version,
                "git_sha": git_sha(),
            },
            "report_artifact": {"path": str(destino), "sha256": report_sha},
        }
        json_path = Path(args.json_out)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

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
