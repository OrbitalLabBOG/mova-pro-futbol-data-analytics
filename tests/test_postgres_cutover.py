from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from mova_fpl.ops.cli import parser
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB
from mova_fpl.ops.postgres_cutover import run_cutover_drill
from mova_fpl.postgres.cutover import ReadCutoverSession
from mova_fpl.postgres.importer import TableSpec
from mova_fpl.postgres.read_repository import PostgresReadRepository, SQLiteReadRepository


class Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class FakePG:
    def __init__(self, rows=None, *, fail=False, artifact_path: Path | None = None):
        self.rows = rows or []
        self.fail = fail
        self.artifact_path = artifact_path

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, _params=None):
        if isinstance(statement, str) and "artifact_path" in statement:
            return Result([{"artifact_path": str(self.artifact_path)}])
        if self.fail:
            raise RuntimeError("candidate unavailable")
        if isinstance(statement, str):
            return Result([{"present": 1}])
        return Result(self.rows)


def _sqlite_repo(tmp_path: Path) -> tuple[SQLiteReadRepository, TableSpec]:
    path = tmp_path / "ops.db"
    con = sqlite3.connect(path)
    con.execute("create table fixture(id integer primary key, enabled integer, payload text)")
    con.execute("insert into fixture values(1,1,'{\"a\":1}')")
    con.commit()
    con.close()
    spec = TableSpec(
        "ops", "fixture", "ops.fixture",
        renames={"payload": "payload"}, json_columns=frozenset({"payload"}),
        bool_columns=frozenset({"enabled"}),
    )
    return SQLiteReadRepository({"ops": path}), spec


def test_read_cutover_returns_to_sqlite_after_candidate_pass(tmp_path: Path):
    sqlite_repo, spec = _sqlite_repo(tmp_path)
    pg = FakePG([{"id": 1, "enabled": True, "payload": {"a": 1}}])
    session = ReadCutoverSession(sqlite_repo, PostgresReadRepository(pg))
    result = session.exercise((spec,))
    assert result["status"] == "pass"
    assert result["sequence"] == [
        "sqlite_baseline", "postgres_candidate", "sqlite_rollback"
    ]
    assert result["rollback_verified"] is True
    assert result["runtime_writer_mutated"] is False
    assert session.active_backend == "sqlite"


def test_read_cutover_rolls_back_after_drift_or_candidate_error(tmp_path: Path):
    sqlite_repo, spec = _sqlite_repo(tmp_path)
    drifted = ReadCutoverSession(
        sqlite_repo,
        PostgresReadRepository(FakePG([
            {"id": 1, "enabled": False, "payload": {"a": 1}}
        ])),
    )
    drift = drifted.exercise((spec,))
    assert drift["status"] == "fail"
    assert drift["checks"][0]["candidate_status"] == "fail"
    assert drift["rollback_verified"] is True
    assert drifted.active_backend == "sqlite"

    broken = ReadCutoverSession(
        sqlite_repo, PostgresReadRepository(FakePG(fail=True))
    )
    failure = broken.exercise((spec,))
    assert failure["status"] == "fail"
    assert failure["candidate_error"] == "RuntimeError"
    assert failure["rollback_verified"] is True
    assert broken.active_backend == "sqlite"


def test_cutover_drill_job_is_idempotent_and_observable(tmp_path: Path, monkeypatch):
    config = RuntimeConfig(
        ops_db=tmp_path / "db" / "ops.db",
        canonical_db=tmp_path / "db" / "canonical.db",
        trace_db=tmp_path / "db" / "trace.db",
        artifact_root=tmp_path / "artifacts",
        postgres_credential_file=tmp_path / "postgres-password",
    )
    db = OpsDB(config.ops_db, enforce_version=False)
    db.migrate()
    db.upsert_cycle("2026-27", 3, "2026-09-04T17:30:00+00:00", phase="preflight")
    imported = config.artifact_root / "postgres-imports" / "fixture"
    imported.mkdir(parents=True)
    monkeypatch.setattr(
        "mova_fpl.ops.postgres_cutover.verify_shadow",
        lambda _config: {
            "status": "pass", "import_run_id": "pgimport_fixture",
            "all_targets_checked": True,
            "read_parity": {"checked_tables": 53, "failed_tables": 0,
                            "content_sha256": "a" * 64},
        },
    )
    monkeypatch.setattr(
        "mova_fpl.ops.postgres_cutover.connect",
        lambda *_args, **_kwargs: FakePG(artifact_path=imported),
    )
    monkeypatch.setattr(
        "mova_fpl.ops.postgres_cutover.connect_readonly",
        lambda *_args, **_kwargs: FakePG(),
    )
    monkeypatch.setattr(
        "mova_fpl.ops.postgres_cutover.ReadCutoverSession.exercise",
        lambda _self: {
            "status": "pass",
            "sequence": ["sqlite_baseline", "postgres_candidate", "sqlite_rollback"],
            "writer_before": "sqlite", "candidate_reader": "postgres",
            "writer_after": "sqlite", "runtime_writer_mutated": False,
            "rollback_verified": True, "candidate_error": None,
            "checks": [{"target": "ops.runtime_controls"}],
        },
    )
    first = run_cutover_drill(
        config, db, actor="test", reason="read path rehearsal", idempotency_key="gw3-v1"
    )
    reused = run_cutover_drill(
        config, db, actor="test", reason="read path rehearsal", idempotency_key="gw3-v1"
    )
    assert first["status"] == "completed"
    assert first["rollback_verified"] is True
    assert reused["status"] == "reused"
    assert reused["job_id"] == first["job_id"]
    with pytest.raises(ValueError, match="idempotency_key"):
        run_cutover_drill(
            config, db, actor="test", reason="different reason",
            idempotency_key="gw3-v1",
        )
    assert Path(first["artifact_path"]).is_file()
    evidence = json.loads(Path(first["artifact_path"]).read_text())
    assert evidence["writer_after"] == "sqlite"
    assert evidence["runtime_writer_mutated"] is False
    metrics = db.prometheus()
    assert 'mova_postgres_cutover_drill_status{status="completed"} 1' in metrics
    assert "mova_postgres_cutover_rollback_verified 1" in metrics


def test_cutover_drill_cli_requires_audited_identity():
    parsed = parser().parse_args([
        "postgres", "drill", "--actor", "operator", "--reason", "rehearsal",
        "--idempotency-key", "gw3-v1",
    ])
    assert parsed.postgres_command == "drill"
    assert parsed.actor == "operator"
