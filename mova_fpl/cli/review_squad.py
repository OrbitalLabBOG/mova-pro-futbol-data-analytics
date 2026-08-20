"""Valida y documenta una plantilla revisada por contexto externo.

El optimizador sigue siendo la linea base cuantitativa. Esta CLI cubre el paso
deliberadamente humano del runbook: incorporar ruedas de prensa, alineaciones
probables y consenso experto sin perder trazabilidad ni las reglas del motor.

No tiene primitivas de red ni escribe en FPL. Consume un snapshot sellado y una
especificacion JSON versionada, proyecta los mismos xP que ``cli.live`` y emite
el acta canonica mediante ``engine.report``.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from mova_fpl.cli.collect_live import load_snapshot
from mova_fpl.cli.live import _dias
from mova_fpl.data import live
from mova_fpl.data.store import Store
from mova_fpl.engine.projection import points_projection
from mova_fpl.engine.report import render
from mova_fpl.engine.state import Decision
from mova_fpl.models.registry import git_sha, load
from mova_fpl.rules import get as get_rules
from mova_fpl.rules.base import Position

ROOT = Path(__file__).resolve().parents[2]


def load_spec(path: Path) -> dict:
    spec = json.loads(path.read_text(encoding="utf-8"))
    required = {"season", "gw", "squad", "starters", "captain", "vice_captain",
                "bench_order"}
    missing = sorted(required - set(spec))
    if missing:
        raise ValueError(f"especificacion incompleta; faltan: {', '.join(missing)}")
    return spec


def build_decision(spec: dict, roster, detail, budget: float) -> Decision:
    """Construye una Decision solo despues de validar la integridad de la spec."""
    squad = tuple(int(e) for e in spec["squad"])
    starters = tuple(int(e) for e in spec["starters"])
    bench = tuple(int(e) for e in spec["bench_order"])
    captain, vice = int(spec["captain"]), int(spec["vice_captain"])

    if len(squad) != 15 or len(set(squad)) != 15:
        raise ValueError("squad debe contener exactamente 15 element IDs unicos")
    if len(starters) != 11 or len(set(starters)) != 11:
        raise ValueError("starters debe contener exactamente 11 element IDs unicos")
    if not set(starters) <= set(squad):
        raise ValueError("todos los titulares deben pertenecer a squad")
    if captain not in starters or vice not in starters or captain == vice:
        raise ValueError("capitan y vice deben ser titulares distintos")
    complement = set(squad) - set(starters)
    if len(bench) != 4 or len(set(bench)) != 4 or set(bench) != complement:
        raise ValueError("bench_order debe ser exactamente el complemento del XI")

    rows = roster.set_index("element", drop=False)
    unknown = sorted(set(squad) - set(rows.index.astype(int)))
    if unknown:
        raise ValueError(f"element IDs ausentes del snapshot: {unknown}")
    if Position.parse(rows.loc[bench[0], "position"]) is not Position.GKP:
        raise ValueError("el primer elemento de bench_order debe ser el portero suplente")

    det = detail.set_index("element")
    missing_projection = sorted(set(squad) - set(det.index.astype(int)))
    if missing_projection:
        raise ValueError(f"element IDs sin proyeccion: {missing_projection}")

    expected = sum(float(det.loc[e, "xp"]) for e in starters) + float(det.loc[captain, "xp"])
    total = sum(float(rows.loc[e, "value"]) / 10.0 for e in squad)
    notes = tuple(str(n) for n in spec.get("rationale", ()))
    return Decision(
        season=str(spec["season"]), gw=int(spec["gw"]), squad_15=squad,
        starters=starters, captain=captain, vice_captain=vice,
        bench_order=bench, expected_points=round(expected, 2),
        total_cost=round(total, 1), bank_after=round(float(budget) - total, 1),
        policy="human-reviewed", notes=notes,
    )


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Valida una plantilla revisada contra snapshot, modelos y reglas FPL")
    ap.add_argument("--snapshot-dir", required=True)
    ap.add_argument("--spec", required=True)
    ap.add_argument("--minutes-version", default="1.1.0")
    ap.add_argument("--version", default="1.1.0", help="version del modelo de puntos")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    snapshot_dir, spec_path = Path(args.snapshot_dir), Path(args.spec)
    spec = load_spec(spec_path)
    season, gw = str(spec["season"]), int(spec["gw"])
    boot, fixtures, manifest = load_snapshot(snapshot_dir)
    if manifest.get("season") != season or int(manifest.get("gw", -1)) != gw:
        raise ValueError("la temporada/GW de la spec no coincide con el snapshot sellado")

    roster = live.roster(boot, fixtures, season, gw)
    history = Store().as_of("2025-26", 39)
    models = {
        "minutes": load("minutes", args.minutes_version),
        "points": load("points", args.version),
    }
    _, detail = points_projection(
        history, roster, models, season, con_desglose=True,
        equipos=live.teams(boot), disponibilidad=roster["disponibilidad"].to_numpy(),
    )
    rules = get_rules(season).SQUAD
    decision = build_decision(spec, roster, detail, float(rules["budget"]))
    emitted = datetime.now(timezone.utc)
    deadline = live.deadline(boot, gw)
    acta = render(decision, roster,
                  detail.set_index("element").loc[list(decision.squad_15)].reset_index(), {
        "season": season,
        "emitida": emitted.isoformat(timespec="seconds"),
        "deadline": deadline,
        "policy": "human-reviewed",
        "horizon": int(spec.get("horizon", 3)),
        "v_minutes": args.minutes_version,
        "v_points": args.version,
        "git_sha": git_sha(),
        "rules": rules,
        "dias_al_deadline": _dias(deadline, emitted),
        "fuente": (f"snapshot sellado {snapshot_dir} · manifest "
                   f"{manifest.get('captured_at', 'sin fecha')} · "
                   f"spec {spec_path}; solo lectura"),
    })
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(acta.texto, encoding="utf-8")
    print(f"acta {'VALIDA' if acta.valida else 'INVALIDA'} · "
          f"coste £{acta.total:.1f}M · banco £{acta.banco:.1f}M · "
          f"xP modelo {decision.expected_points:.1f} · huella {decision.fingerprint()}")
    print(out)
    if not acta.valida:
        for violation in acta.violaciones:
            print(f"  {violation.code}: {violation.detail}")
        raise SystemExit(2)


if __name__ == "__main__":
    main()
