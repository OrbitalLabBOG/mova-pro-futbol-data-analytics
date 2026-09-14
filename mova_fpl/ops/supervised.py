"""Importa una operación browser supervisada después de verificar su evidencia.

Este módulo no opera FPL. Persiste únicamente una ejecución ya realizada y
contrastada contra el artefacto autenticado de estado del equipo.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from mova_fpl.data.private_state import validate as validate_private_state
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB, canonical_json, new_id, sha256_json


SCHEMA_V1 = "mova-fpl-supervised-execution-v1"
SCHEMA = "mova-fpl-manual-verified-execution-v2"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _utc(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} debe ser RFC3339") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} debe incluir zona horaria")
    return parsed.astimezone(timezone.utc)


def _load_team_state(reference: dict) -> tuple[Path, dict, dict]:
    directory = Path(reference["artifact_path"])
    path = directory / "team-state.json"
    if not path.is_file():
        raise FileNotFoundError(path)
    if _sha256(path) != reference["payload_sha256"]:
        raise ValueError("hash del estado privado no coincide")
    normalized, quality = validate_private_state(
        json.loads(path.read_text(encoding="utf-8"))
    )
    if reference.get("fingerprint") and reference["fingerprint"] != quality["fingerprint"]:
        raise ValueError("fingerprint declarado del estado privado no coincide")
    return path, normalized, quality


def _assert_v2_artifacts_under_root(package: dict, artifact_root: Path) -> None:
    paths = {
        "decision.artifact_path": Path(package["decision"]["artifact_path"]),
        "execution.evidence_path": Path(package["execution"]["evidence_path"]),
        "pre_team_state.artifact_path": Path(package["pre_team_state"]["artifact_path"]),
        "post_team_state.artifact_path": Path(package["post_team_state"]["artifact_path"]),
    }
    root = artifact_root.resolve()
    for field, path in paths.items():
        if not path.resolve().is_relative_to(root):
            raise ValueError(f"{field} debe estar dentro de MOVA_ARTIFACT_ROOT")


def _validate_players(decision: dict) -> tuple[list[dict], list[int]]:
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
    return players, elements


def _validate_v1(package: dict) -> tuple[Path, Path, Path]:
    if package.get("schema") != SCHEMA_V1:
        raise ValueError(f"schema inesperado: {package.get('schema')!r}")
    if package.get("cycle_id") != f"{package.get('season')}-gw{int(package.get('gw')):02d}":
        raise ValueError("cycle_id no coincide con season/gw")

    auth = package["authorization"]
    if auth.get("transfers_allowed") or auth.get("chips_allowed"):
        raise ValueError("este importador sólo admite A1 sin transfers ni chips")
    if auth.get("action_level") != "A1":
        raise ValueError("action_level debe ser A1")

    decision = package["decision"]
    players, elements = _validate_players(decision)
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


def _validate_v2(package: dict) -> dict:
    if package.get("cycle_id") != f"{package.get('season')}-gw{int(package.get('gw')):02d}":
        raise ValueError("cycle_id no coincide con season/gw")
    authorization = package["authorization"]
    action_level = authorization.get("action_level")
    risk_class = authorization.get("risk_class")
    expected = {"A2": "R2", "A3": "R3"}
    if action_level not in expected or risk_class != expected[action_level]:
        raise ValueError("autoridad debe mapear R2/A2 o R3/A3")
    if not str(authorization.get("authorized_by") or "").strip():
        raise ValueError("authorized_by es obligatorio")
    policy_version = str(authorization.get("policy_version") or "").strip()
    if not policy_version:
        raise ValueError("authorization.policy_version es obligatorio")
    allowed = set(authorization.get("allowed_operations") or ())
    valid_operations = {"lineup", "captaincy", "transfers", "hits", "chip"}
    if not allowed or not allowed <= valid_operations:
        raise ValueError("allowed_operations contiene operaciones inválidas")
    if risk_class == "R2" and allowed - {"lineup", "captaincy"}:
        raise ValueError("R2 sólo puede autorizar lineup/captaincy")
    authorized_at = _utc(authorization["authorized_at"], "authorized_at")
    expires_at = _utc(authorization["expires_at"], "expires_at")
    deadline = _utc(package["deadline_at"], "deadline_at")
    execution = package["execution"]
    started_at = _utc(execution["started_at"], "execution.started_at")
    finished_at = _utc(execution["finished_at"], "execution.finished_at")
    if not authorized_at <= started_at <= finished_at <= expires_at <= deadline:
        raise ValueError("ventana de autorización/ejecución inválida")
    if execution.get("status") != "verified" or execution.get("action_level") != action_level:
        raise ValueError("execution debe estar verified y usar el action_level autorizado")

    decision = package["decision"]
    if decision.get("status") != "executed_verified":
        raise ValueError("decision.status debe ser executed_verified")
    if decision.get("policy_version") != policy_version:
        raise ValueError("la política de decisión no coincide con la autorización")
    if decision.get("mode") not in {"supervised", "guarded_human_reviewed"}:
        raise ValueError("decision.mode no representa una operación humana supervisada")
    players, elements = _validate_players(decision)
    checks = package.get("verification_checks") or []
    required_checks = {"authorization", "pre_state", "post_reload_state", "exact_diff"}
    passed_checks = {str(check.get("check_name")) for check in checks if check.get("passed") is True}
    if not required_checks <= passed_checks or not all(check.get("passed") is True for check in checks):
        raise ValueError("faltan verificaciones obligatorias aprobadas")

    decision_path = Path(decision["artifact_path"])
    evidence_path = Path(execution["evidence_path"])
    for path, digest in (
        (decision_path, decision["manifest_sha256"]),
        (evidence_path, execution["evidence_sha256"]),
    ):
        if not path.is_file():
            raise FileNotFoundError(path)
        if _sha256(path) != digest:
            raise ValueError(f"hash no coincide para {path.name}")

    pre_path, pre, pre_quality = _load_team_state(package["pre_team_state"])
    post_path, post, post_quality = _load_team_state(package["post_team_state"])
    gw = int(package["gw"])
    if int(pre["event"]["id"]) != gw or int(post["event"]["id"]) != gw:
        raise ValueError("pre/post-state no corresponden a la GW")
    if _utc(pre["event"]["deadline_time"], "pre.deadline_time") != deadline or _utc(
        post["event"]["deadline_time"], "post.deadline_time"
    ) != deadline:
        raise ValueError("deadline del paquete no coincide con pre/post-state")
    if pre["team_id"] != post["team_id"]:
        raise ValueError("pre/post-state no corresponden al mismo equipo")
    if not _utc(pre["observed_at"], "pre.observed_at") <= started_at:
        raise ValueError("pre-state fue observado después de iniciar")
    if not finished_at <= _utc(post["observed_at"], "post.observed_at"):
        raise ValueError("post-state precede la finalización")

    post_picks = sorted(post["picks"], key=lambda pick: int(pick["position"]))
    if [int(pick["element"]) for pick in post_picks] != elements:
        raise ValueError("las posiciones post-reload no coinciden con la decisión")
    captain = next(player for player in players if player["is_captain"])
    vice = next(player for player in players if player["is_vice_captain"])
    post_captain = next(pick for pick in post_picks if pick["is_captain"])
    post_vice = next(pick for pick in post_picks if pick["is_vice_captain"])
    if int(post_captain["element"]) != int(captain["element"]):
        raise ValueError("capitanía post-reload no coincide")
    if int(post_vice["element"]) != int(vice["element"]):
        raise ValueError("vicecapitanía post-reload no coincide")
    expected_captain_multiplier = 3 if decision.get("chip") == "3xc" else 2
    if int(post_captain["multiplier"]) != expected_captain_multiplier:
        raise ValueError("multiplicador de capitán post-reload no coincide")
    if int(post_vice["multiplier"]) != 1:
        raise ValueError("multiplicador de vicecapitán post-reload no coincide")
    if decision.get("fingerprint") != post_quality["fingerprint"]:
        raise ValueError("fingerprint de decisión no coincide con post-state")

    transfer_diff = decision.get("transfers") or {"out": [], "in": [], "hits": 0}
    declared_out = sorted(int(value) for value in transfer_diff.get("out") or ())
    declared_in = sorted(int(value) for value in transfer_diff.get("in") or ())
    pre_elements = {int(pick["element"]) for pick in pre["picks"]}
    post_elements = {int(pick["element"]) for pick in post["picks"]}
    if declared_out != sorted(pre_elements - post_elements) or declared_in != sorted(post_elements - pre_elements):
        raise ValueError("diff de transferencias no coincide con pre/post-state")
    if len(declared_out) != len(declared_in):
        raise ValueError("transferencias in/out desbalanceadas")
    hits = int(transfer_diff.get("hits", 0))
    if hits < 0 or hits % 4:
        raise ValueError("hits debe ser un coste no negativo múltiplo de cuatro")
    chip = decision.get("chip")
    if risk_class == "R2" and (declared_out or declared_in or hits or chip is not None):
        raise ValueError("R2 no puede registrar transferencias, hits o chip")
    if (declared_out or declared_in or hits) and "transfers" not in allowed:
        raise ValueError("la autorización no cubre transferencias")
    if hits and "hits" not in allowed:
        raise ValueError("la autorización no cubre hits")
    if chip is not None and "chip" not in allowed:
        raise ValueError("la autorización no cubre chip")
    if chip is not None:
        if chip not in {"wildcard", "freehit", "bboost", "3xc"}:
            raise ValueError("chip desconocido")
        pre_chips = {row["name"]: row["status_for_entry"] for row in pre["chips"]}
        post_chips = {row["name"]: row["status_for_entry"] for row in post["chips"]}
        if pre_chips.get(chip) != "available" or post_chips.get(chip) == "available":
            raise ValueError("pre/post-state no acredita el uso del chip")

    return {
        "decision_path": decision_path, "evidence_path": evidence_path,
        "pre_state_path": pre_path, "post_state_path": post_path,
        "pre_fingerprint": pre_quality["fingerprint"],
        "post_fingerprint": post_quality["fingerprint"],
        "action_level": action_level, "risk_class": risk_class,
        "authorized_by": authorization["authorized_by"],
        "allowed_operations": sorted(allowed),
        "transfers_in": declared_in,
        "transfers_out": declared_out,
        "hits": hits,
        "chip": chip,
    }


def record(package_path: Path, *, actor: str = "codex", reason: str = "legacy import",
           idempotency_key: str | None = None) -> dict:
    package = json.loads(package_path.read_text(encoding="utf-8"))
    if not actor.strip() or not reason.strip():
        raise ValueError("actor y reason son obligatorios")
    config = RuntimeConfig.from_env()
    config.validate()
    if package.get("schema") == SCHEMA:
        _assert_v2_artifacts_under_root(package, config.artifact_root)
        validation = _validate_v2(package)
    elif package.get("schema") == SCHEMA_V1:
        _validate_v1(package)
        validation = {
            "action_level": "A1", "risk_class": "legacy",
            "authorized_by": package["actor"], "allowed_operations": ["legacy_lineup"],
            "pre_fingerprint": None,
            "post_fingerprint": package["decision"]["fingerprint"],
            "transfers_in": [], "transfers_out": [], "hits": 0,
            "chip": None,
        }
    else:
        raise ValueError(f"schema inesperado: {package.get('schema')!r}")
    package_sha = _sha256(package_path)
    db = OpsDB(config.ops_db, minimum_version=config.sqlite_min_version)
    db.migrate()

    cycle_id = package["cycle_id"]
    decision = package["decision"]
    strategy = package["strategy"]
    execution = package["execution"]
    correlation_id = f"corr_gw{int(package['gw']):02d}_{package_sha[:16]}"
    idempotency_key = idempotency_key or f"supervised-execution:{cycle_id}:{package_sha}"
    job_type = "manual_verified_execution" if package.get("schema") == SCHEMA else "supervised_execution"
    job_id, reused = db.start_job(
        job_type,
        idempotency_key,
        correlation_id,
        cycle_id=cycle_id,
        input_sha256=package_sha,
    )
    if reused:
        reused_job = db.get_job_by_key(idempotency_key)
        if not reused_job or reused_job.get("input_sha256") != package_sha:
            raise ValueError("idempotency_key ya usada con otro contenido")
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
            "action_level": validation["action_level"],
            "risk_class": validation["risk_class"],
            "cycle_latched": True,
        }

    try:
        with db.transaction() as con:
            if not con.execute(
                "SELECT 1 FROM gameweek_cycles WHERE cycle_id=?", (cycle_id,)
            ).fetchone():
                raise ValueError(f"ciclo inexistente: {cycle_id}")
            prior_verified = con.execute(
                """SELECT e.execution_id,d.decision_id,e.evidence_sha256
                FROM web_executions e JOIN decision_runs d ON d.decision_id=e.decision_id
                WHERE d.cycle_id=? AND e.status='verified'
                ORDER BY e.finished_at DESC,e.rowid DESC LIMIT 1""", (cycle_id,),
            ).fetchone()
            if prior_verified:
                raise RuntimeError(
                    "el ciclo ya tiene una ejecución verificada; usar el replay idempotente"
                )
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
                    transfer_direction,expected_points) VALUES(?,?,?,?,?,?,?,NULL)""",
                    (
                        decision["decision_id"], int(player["element"]),
                        int(player["squad_position"]), player["role"],
                        int(player["is_captain"]), int(player["is_vice_captain"]),
                        "in" if int(player["element"]) in validation["transfers_in"] else None,
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
                    validation["action_level"], execution["envelope_sha256"],
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
                "manual_verified_execution_recorded" if package.get("schema") == SCHEMA
                else "supervised_execution_verified",
                actor=actor,
                correlation_id=correlation_id,
                cycle_id=cycle_id,
                job_id=job_id,
                subject_type="web_execution",
                subject_id=execution["execution_id"],
                payload={
                    "authorized_by": validation["authorized_by"],
                    "record_reason": reason,
                    "action_level": validation["action_level"],
                    "risk_class": validation["risk_class"],
                    "allowed_operations": validation["allowed_operations"],
                    "pre_fingerprint": validation["pre_fingerprint"],
                    "post_fingerprint": validation["post_fingerprint"],
                    "decision_id": decision["decision_id"],
                    "decision_manifest_sha256": decision["manifest_sha256"],
                    "operation_package_sha256": package_sha,
                    "team_state_id": (
                        package.get("post_team_state", {}).get("team_state_id")
                        or package.get("observed_team_state", {}).get("team_state_id")
                    ),
                    "transfers_in": validation["transfers_in"],
                    "transfers_out": validation["transfers_out"],
                    "hits": validation["hits"],
                    "chip": validation["chip"],
                    "strategy_status": strategy["status"],
                    "strategy_rationale": strategy["rationale"],
                    "chip_candidate_ev_status": "not_estimated",
                    "superseded_shadow_decisions": superseded,
                    "verification_checks": len(package["verification_checks"]),
                },
                con=con,
            )
            con.execute(
                """UPDATE gameweek_cycles SET phase='executed_verified',
                status='executed_verified',last_observed_at=?,revision=revision+1
                WHERE cycle_id=?""", (execution["finished_at"], cycle_id),
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
            "action_level": validation["action_level"],
            "risk_class": validation["risk_class"],
            "cycle_latched": True,
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
    parser.add_argument("--actor", default="codex")
    parser.add_argument("--reason", default="legacy import")
    parser.add_argument("--idempotency-key")
    args = parser.parse_args()
    print(json.dumps(record(
        args.package, actor=args.actor, reason=args.reason,
        idempotency_key=args.idempotency_key,
    ), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
