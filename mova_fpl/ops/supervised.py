"""Importa una operación browser supervisada después de verificar su evidencia.

Este módulo no opera FPL. Persiste únicamente una ejecución ya realizada y
contrastada contra el artefacto autenticado de estado del equipo.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from mova_fpl.data.private_state import validate as validate_private_state
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB, canonical_json, new_id, sha256_json


SCHEMA = "mova-fpl-supervised-execution-v1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate(package: dict) -> tuple[Path, Path, Path]:
    if package.get("schema") != SCHEMA:
        raise ValueError(f"schema inesperado: {package.get('schema')!r}")
    if package.get("cycle_id") != f"{package.get('season')}-gw{int(package.get('gw')):02d}":
        raise ValueError("cycle_id no coincide con season/gw")

    auth = package["authorization"]
    if auth.get("transfers_allowed") or auth.get("chips_allowed"):
        raise ValueError("este importador sólo admite A1 sin transfers ni chips")
    if auth.get("action_level") != "A1":
        raise ValueError("action_level debe ser A1")

    decision = package["decision"]
    players = decision["players"]
    positions = [int(player["squad_position"]) for player in players]
    elements = [int(player["element"]) for player in players]
    if len(players) != 15 or sorted(positions) != list(range(1, 16)):
        raise ValueError("la decisión debe contener exactamente las posiciones 1..15")
    if len(set(elements)) != 15:
        raise ValueError("la decisión contiene elements duplicados")
    if sum(bool(player["is_captain"]) for player in players) != 1:
        raise ValueError("se requiere exactamente un capitán")
    if sum(bool(player["is_vice_captain"]) for player in players) != 1:
        raise ValueError("se requiere exactamente un vicecapitán")
    for player in players:
        expected_role = "starter" if int(player["squad_position"]) <= 11 else "bench"
        if player["role"] != expected_role:
            raise ValueError(f"role inválido para position {player['squad_position']}")
        if (player["is_captain"] or player["is_vice_captain"]) and expected_role != "starter":
            raise ValueError("capitán y vicecapitán deben ser titulares")
    if decision.get("chip") is not None:
        raise ValueError("una operación A1 no puede registrar chip")
    if not package.get("verification_checks") or not all(
        check.get("passed") is True for check in package["verification_checks"]
    ):
        raise ValueError("todas las verificaciones deben existir y estar aprobadas")

    decision_path = Path(decision["artifact_path"])
    evidence_path = Path(package["execution"]["evidence_path"])
    team_state_dir = Path(package["observed_team_state"]["artifact_path"])
    team_state_path = team_state_dir / "team-state.json"
    for path in (decision_path, evidence_path, team_state_path):
        if not path.is_file():
            raise FileNotFoundError(path)
    if _sha256(decision_path) != decision["manifest_sha256"]:
        raise ValueError("hash del artefacto de decisión no coincide")
    if _sha256(evidence_path) != package["execution"]["evidence_sha256"]:
        raise ValueError("hash de evidencia browser no coincide")
    if _sha256(team_state_path) != package["observed_team_state"]["payload_sha256"]:
        raise ValueError("hash del estado privado no coincide")

    observed, private_quality = validate_private_state(
        json.loads(team_state_path.read_text(encoding="utf-8"))
    )
    observed_picks = sorted(observed["picks"], key=lambda pick: int(pick["position"]))
    if [int(pick["element"]) for pick in observed_picks] != elements:
        raise ValueError("las posiciones privadas no coinciden con la decisión")
    captain = next(player for player in players if player["is_captain"])
    vice = next(player for player in players if player["is_vice_captain"])
    observed_captain = next(pick for pick in observed_picks if pick["is_captain"])
    observed_vice = next(pick for pick in observed_picks if pick["is_vice_captain"])
    if int(observed_captain["element"]) != int(captain["element"]) or int(
        observed_captain["multiplier"]
    ) != 2:
        raise ValueError("capitanía privada no coincide")
    if int(observed_vice["element"]) != int(vice["element"]):
        raise ValueError("vicecapitanía privada no coincide")
    if int(observed["transfers"]["made"]) != 0 or observed.get("active_chip") is not None:
        raise ValueError("el estado privado muestra transfer o chip inesperado")
    if private_quality["fingerprint"] != decision["fingerprint"]:
        raise ValueError("fingerprint privado no coincide")
    return decision_path, evidence_path, team_state_path


def record(package_path: Path) -> dict:
    package = json.loads(package_path.read_text(encoding="utf-8"))
    _validate(package)
    package_sha = _sha256(package_path)
    config = RuntimeConfig.from_env()
    config.validate()
    db = OpsDB(config.ops_db, minimum_version=config.sqlite_min_version)
    db.migrate()

    cycle_id = package["cycle_id"]
    decision = package["decision"]
    strategy = package["strategy"]
    execution = package["execution"]
    correlation_id = f"corr_gw{int(package['gw']):02d}_{package_sha[:16]}"
    idempotency_key = f"supervised-execution:{cycle_id}:{package_sha}"
    job_id, reused = db.start_job(
        "supervised_execution",
        idempotency_key,
        correlation_id,
        cycle_id=cycle_id,
        input_sha256=package_sha,
    )
    if reused:
        with db.connect(readonly=True) as con:
            found = con.execute(
                "SELECT revision,status FROM decision_runs WHERE decision_id=?",
                (decision["decision_id"],),
            ).fetchone()
        if not found:
            raise RuntimeError("job idempotente existe pero la decisión no fue persistida")
        return {
            "status": "reused",
            "job_id": job_id,
            "decision_id": decision["decision_id"],
            "revision": int(found["revision"]),
        }

    try:
        with db.transaction() as con:
            if not con.execute(
                "SELECT 1 FROM gameweek_cycles WHERE cycle_id=?", (cycle_id,)
            ).fetchone():
                raise ValueError(f"ciclo inexistente: {cycle_id}")
            revision = int(
                con.execute(
                    "SELECT COALESCE(MAX(revision),0)+1 FROM decision_runs WHERE cycle_id=?",
                    (cycle_id,),
                ).fetchone()[0]
            )
            superseded = con.execute(
                "UPDATE decision_runs SET status='superseded' "
                "WHERE cycle_id=? AND status='staged'",
                (cycle_id,),
            ).rowcount
            con.execute(
                """INSERT INTO decision_runs(
                decision_id,job_id,cycle_id,revision,mode,policy_version,status,
                expected_points,chip,fingerprint,manifest_sha256,artifact_path,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    decision["decision_id"], job_id, cycle_id, revision, decision["mode"],
                    decision["policy_version"], decision["status"],
                    decision.get("expected_points"), decision.get("chip"),
                    decision["fingerprint"], decision["manifest_sha256"],
                    decision["artifact_path"], execution["finished_at"],
                ),
            )
            for player in decision["players"]:
                con.execute(
                    """INSERT INTO decision_players(
                    decision_id,element,squad_position,role,is_captain,is_vice_captain,
                    transfer_direction,expected_points) VALUES(?,?,?,?,?,?,NULL,NULL)""",
                    (
                        decision["decision_id"], int(player["element"]),
                        int(player["squad_position"]), player["role"],
                        int(player["is_captain"]), int(player["is_vice_captain"]),
                    ),
                )
            con.execute(
                """INSERT INTO chip_strategy_runs(
                strategy_id,job_id,cycle_id,window_name,policy_version,inventory_json,
                recommended_chip,status,manifest_sha256,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    strategy["strategy_id"], job_id, cycle_id, strategy["window_name"],
                    strategy["policy_version"], canonical_json(strategy["inventory"]),
                    strategy.get("recommended_chip"), strategy["status"],
                    strategy["manifest_sha256"], execution["finished_at"],
                ),
            )
            con.execute(
                """INSERT INTO web_executions(
                execution_id,decision_id,action_level,envelope_sha256,status,started_at,
                finished_at,evidence_path,evidence_sha256) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    execution["execution_id"], decision["decision_id"],
                    execution["action_level"], execution["envelope_sha256"],
                    execution["status"], execution["started_at"], execution["finished_at"],
                    execution["evidence_path"], execution["evidence_sha256"],
                ),
            )
            for check in package["verification_checks"]:
                con.execute(
                    """INSERT INTO verification_checks(
                    check_id,execution_id,check_name,expected_json,observed_json,passed,checked_at)
                    VALUES(?,?,?,?,?,?,?)""",
                    (
                        check["check_id"], execution["execution_id"], check["check_name"],
                        canonical_json(check["expected"]), canonical_json(check["observed"]),
                        int(check["passed"]), execution["finished_at"],
                    ),
                )
            db.append_audit(
                "supervised_execution_verified",
                actor="codex",
                correlation_id=correlation_id,
                cycle_id=cycle_id,
                job_id=job_id,
                subject_type="web_execution",
                subject_id=execution["execution_id"],
                payload={
                    "authorized_by": package["actor"],
                    "decision_id": decision["decision_id"],
                    "decision_manifest_sha256": decision["manifest_sha256"],
                    "operation_package_sha256": package_sha,
                    "team_state_id": package["observed_team_state"]["team_state_id"],
                    "strategy_status": strategy["status"],
                    "strategy_rationale": strategy["rationale"],
                    "chip_candidate_ev_status": "not_estimated",
                    "superseded_shadow_decisions": superseded,
                    "verification_checks": len(package["verification_checks"]),
                },
                con=con,
            )
        output = {
            "status": "completed",
            "job_id": job_id,
            "decision_id": decision["decision_id"],
            "decision_revision": revision,
            "strategy_id": strategy["strategy_id"],
            "execution_id": execution["execution_id"],
            "decision_players": len(decision["players"]),
            "verification_checks": len(package["verification_checks"]),
            "superseded_shadow_decisions": superseded,
            "operation_package_sha256": package_sha,
        }
        db.finish_job(job_id, "completed", output_sha256=sha256_json(output), metrics=output)
        db.quick_check()
        return output
    except Exception as exc:
        db.finish_job(
            job_id,
            "failed",
            error_code=type(exc).__name__,
            error_detail=str(exc)[:2000],
        )
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(record(args.package), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
