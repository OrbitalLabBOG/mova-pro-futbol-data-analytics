from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from mova_fpl.data.private_state import validate as validate_private_state
from mova_fpl.ops.db import OpsDB
from mova_fpl.ops.supervised import SCHEMA, record


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _state(order: list[int], *, observed_at: str, captain: int, vice: int) -> dict:
    types = {1: 1, 15: 1, **{n: 2 for n in range(2, 7)},
             **{n: 3 for n in range(7, 12)}, **{n: 4 for n in range(12, 15)}}
    return {
        "schema": "mova-fpl-private-team-state-v1",
        "observed_at": observed_at,
        "team_id": 3609854,
        "event": {"id": 5, "deadline_time": "2026-09-18T17:30:00Z"},
        "picks_last_updated": observed_at,
        "picks": [
            {"element": element, "element_type": types[element], "position": position,
             "multiplier": 2 if element == captain else 1 if position <= 11 else 0,
             "is_captain": element == captain, "is_vice_captain": element == vice,
             "purchase_price": 50, "selling_price": 50}
            for position, element in enumerate(order, start=1)
        ],
        "transfers": {"bank": 0, "value": 1000, "limit": 2, "made": 0,
                      "cost": 0, "status": "cost"},
        "chips": [
            {"name": name, "number": 1, "status_for_entry": "available",
             "is_pending": False, "start_event": None, "stop_event": None}
            for name in ("wildcard", "freehit", "bboost", "3xc")
        ],
    }


def _write_state(root: Path, name: str, state: dict) -> dict:
    directory = root / name
    directory.mkdir(parents=True)
    path = directory / "team-state.json"
    path.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
    _, quality = validate_private_state(state)
    return {"artifact_path": str(directory), "payload_sha256": _digest(path),
            "fingerprint": quality["fingerprint"]}


def _package(tmp_path: Path) -> tuple[Path, dict]:
    pre = _state(list(range(1, 16)), observed_at="2026-09-17T12:00:00Z",
                 captain=1, vice=2)
    post = _state([*range(1, 11), 12, 11, 13, 14, 15],
                  observed_at="2026-09-17T12:03:00Z", captain=7, vice=8)
    pre_ref = _write_state(tmp_path, "pre", pre)
    post_ref = _write_state(tmp_path, "post", post)
    decision_artifact = tmp_path / "decision.json"
    evidence_artifact = tmp_path / "evidence.json"
    decision_artifact.write_text("{}\n", encoding="utf-8")
    evidence_artifact.write_text("{}\n", encoding="utf-8")
    players = []
    for position, element in enumerate([*range(1, 11), 12, 11, 13, 14, 15], start=1):
        players.append({
            "element": element, "squad_position": position,
            "role": "starter" if position <= 11 else "bench",
            "is_captain": element == 7, "is_vice_captain": element == 8,
        })
    package = {
        "schema": SCHEMA, "season": "2026-27", "gw": 5,
        "cycle_id": "2026-27-gw05", "deadline_at": "2026-09-18T17:30:00Z",
        "authorization": {
            "action_level": "A2", "risk_class": "R2", "authorized_by": "julian",
            "policy_version": "autonomy-policy-1.0.0",
            "authorized_at": "2026-09-17T11:55:00Z",
            "expires_at": "2026-09-17T12:10:00Z",
            "allowed_operations": ["lineup", "captaincy"],
        },
        "decision": {
            "decision_id": "decision_manual_gw05", "mode": "guarded_human_reviewed",
            "policy_version": "autonomy-policy-1.0.0", "status": "executed_verified",
            "expected_points": None, "chip": None, "transfers": {"out": [], "in": [], "hits": 0},
            "fingerprint": post_ref["fingerprint"], "players": players,
            "artifact_path": str(decision_artifact),
            "manifest_sha256": _digest(decision_artifact),
        },
        "strategy": {
            "strategy_id": "strategy_manual_gw05", "window_name": "gw05",
            "policy_version": "autonomy-policy-1.0.0", "inventory": {},
            "recommended_chip": None, "status": "hold_verified",
            "manifest_sha256": "a" * 64, "rationale": "operación humana verificada",
        },
        "execution": {
            "execution_id": "execution_manual_gw05", "action_level": "A2",
            "envelope_sha256": "b" * 64, "status": "verified",
            "started_at": "2026-09-17T12:01:00Z",
            "finished_at": "2026-09-17T12:02:00Z",
            "evidence_path": str(evidence_artifact),
            "evidence_sha256": _digest(evidence_artifact),
        },
        "pre_team_state": pre_ref, "post_team_state": post_ref,
        "verification_checks": [
            {"check_id": f"check_{name}", "check_name": name,
             "expected": True, "observed": True, "passed": True}
            for name in ("authorization", "pre_state", "post_reload_state", "exact_diff")
        ],
    }
    package_path = tmp_path / "manual.json"
    package_path.write_text(json.dumps(package, sort_keys=True) + "\n", encoding="utf-8")
    return package_path, package


def _runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> OpsDB:
    db_path = tmp_path / "ops.db"
    monkeypatch.setenv("MOVA_OPS_DB", str(db_path))
    monkeypatch.setenv("MOVA_ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("MOVA_SQLITE_MIN_VERSION", "3.0.0")
    db = OpsDB(db_path, enforce_version=False)
    db.migrate()
    db.upsert_cycle("2026-27", 5, "2026-09-18T17:30:00Z", phase="execution")
    return db


def test_manual_verified_r2_records_latch_and_is_idempotent(tmp_path, monkeypatch):
    package_path, _ = _package(tmp_path)
    db = _runtime(monkeypatch, tmp_path)
    result = record(package_path, actor="operator", reason="registro supervisado",
                    idempotency_key="manual:gw05:v1")
    assert result["status"] == "completed"
    assert result["action_level"] == "A2"
    assert result["cycle_latched"] is True
    replay = record(package_path, actor="operator", reason="registro supervisado",
                    idempotency_key="manual:gw05:v1")
    assert replay["status"] == "reused"
    changed = json.loads(package_path.read_text(encoding="utf-8"))
    changed["strategy"]["rationale"] = "contenido distinto"
    package_path.write_text(json.dumps(changed, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="idempotency_key ya usada con otro contenido"):
        record(package_path, actor="operator", reason="registro supervisado",
               idempotency_key="manual:gw05:v1")
    with db.connect(readonly=True) as con:
        assert tuple(con.execute(
            "SELECT phase,status FROM gameweek_cycles WHERE cycle_id='2026-27-gw05'"
        ).fetchone()) == ("executed_verified", "executed_verified")
        assert con.execute(
            "SELECT event_type FROM audit_events WHERE subject_id='execution_manual_gw05'"
        ).fetchone()[0] == "manual_verified_execution_recorded"


def test_manual_verified_rejects_second_execution_and_r2_transfer(tmp_path, monkeypatch):
    package_path, package = _package(tmp_path)
    _runtime(monkeypatch, tmp_path)
    record(package_path, actor="operator", reason="primera", idempotency_key="manual:first")
    package["decision"]["decision_id"] = "decision_other"
    package["execution"]["execution_id"] = "execution_other"
    second = tmp_path / "second.json"
    second.write_text(json.dumps(package, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="ya tiene una ejecución verificada"):
        record(second, actor="operator", reason="segunda", idempotency_key="manual:second")

    package_path, package = _package(tmp_path / "invalid")
    package["decision"]["transfers"] = {"out": [2], "in": [16], "hits": 0}
    package_path.write_text(json.dumps(package, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="diff de transferencias"):
        record(package_path, actor="operator", reason="inválida",
               idempotency_key="manual:invalid")


def test_manual_verified_rejects_artifacts_outside_private_root(tmp_path, monkeypatch):
    package_path, _ = _package(tmp_path / "outside")
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    monkeypatch.setenv("MOVA_OPS_DB", str(allowed_root / "ops.db"))
    monkeypatch.setenv("MOVA_ARTIFACT_ROOT", str(allowed_root))
    monkeypatch.setenv("MOVA_SQLITE_MIN_VERSION", "3.0.0")
    with pytest.raises(ValueError, match="debe estar dentro de MOVA_ARTIFACT_ROOT"):
        record(package_path, actor="operator", reason="ruta inválida",
               idempotency_key="manual:outside")
