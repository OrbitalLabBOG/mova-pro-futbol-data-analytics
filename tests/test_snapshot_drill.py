from __future__ import annotations

import json
import hashlib
from pathlib import Path

from mova_fpl.ops.cli import main, parser
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB
from mova_fpl.ops.snapshot_drill import run
from mova_fpl.postgres.importer import _verify_manifest


def test_snapshot_rejection_drill_covers_integrity_and_path_boundaries():
    result = run()

    assert result["schema"] == "mova-snapshot-rejection-drill-v1"
    assert result["status"] == "pass"
    assert result["runtime_mutated"] is False
    assert result["fixture_only"] is True
    assert result["checks"] == {
        "valid_baseline_accepted": True,
        "manifest_checksum_rejected": True,
        "manifest_contract_rejected": True,
        "database_checksum_rejected": True,
        "corrupt_database_rejected": True,
        "size_mismatch_rejected": True,
        "duplicate_name_rejected": True,
        "path_traversal_rejected": True,
        "symlink_rejected": True,
        "temporary_workspace_removed": True,
    }


def test_snapshot_drill_cli_is_audited_idempotent_and_identity_bound(
    tmp_path: Path, monkeypatch, capsys,
):
    config = RuntimeConfig(
        ops_db=tmp_path / "db" / "ops.db",
        artifact_root=tmp_path / "artifacts",
        git_sha="snapshot-test",
        sqlite_min_version="3.40.0",
    )
    config.ops_db.parent.mkdir(parents=True)
    db = OpsDB(config.ops_db, minimum_version=config.sqlite_min_version)
    db.migrate()
    monkeypatch.setattr(
        RuntimeConfig, "from_env", classmethod(lambda cls: config),
    )
    arguments = [
        "drill", "snapshot", "--actor", "operator",
        "--reason", "snapshot boundary", "--idempotency-key", "snapshot-1",
    ]

    assert main(arguments) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["status"] == "pass"
    assert first["job_id"]
    assert db.snapshot_rejection_drill_status()["passed"] == 10

    assert main(arguments) == 0
    replay = json.loads(capsys.readouterr().out)
    assert replay == {
        "schema": "mova-snapshot-rejection-drill-v1",
        "status": "reused",
        "job_id": first["job_id"],
    }

    conflict_args = [*arguments]
    conflict_args[conflict_args.index("snapshot boundary")] = "different reason"
    assert main(conflict_args) == 2
    conflict = json.loads(capsys.readouterr().out)
    assert conflict["status"] == "conflict"
    assert conflict["error_code"] == "idempotency_identity_mismatch"


def test_snapshot_drill_parser_requires_audit_identity():
    parsed = parser().parse_args([
        "drill", "snapshot", "--actor", "operator", "--reason", "boundary",
        "--idempotency-key", "snapshot-1",
    ])
    assert parsed.drill_command == "snapshot"


def test_non_object_manifest_fails_closed_without_exception(tmp_path: Path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text("[]\n", encoding="utf-8")
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()

    result = _verify_manifest(tmp_path, digest)

    assert result == {"status": "fail", "reason": "manifest_contract_invalid"}


def test_failed_snapshot_drill_never_replays_as_success(
    tmp_path: Path, monkeypatch, capsys,
):
    import mova_fpl.ops.snapshot_drill as snapshot_module

    config = RuntimeConfig(
        ops_db=tmp_path / "db" / "ops.db",
        artifact_root=tmp_path / "artifacts",
        sqlite_min_version="3.40.0",
    )
    config.ops_db.parent.mkdir(parents=True)
    OpsDB(config.ops_db, minimum_version=config.sqlite_min_version).migrate()
    monkeypatch.setattr(
        RuntimeConfig, "from_env", classmethod(lambda cls: config),
    )
    monkeypatch.setattr(snapshot_module, "run", lambda: {
        "schema": "mova-snapshot-rejection-drill-v1",
        "scenario": "snapshot_rejection", "status": "fail",
        "checks": {"expected_rejection": False}, "runtime_mutated": False,
    })
    arguments = [
        "drill", "snapshot", "--actor", "operator", "--reason", "failure path",
        "--idempotency-key", "snapshot-failed",
    ]

    assert main(arguments) == 1
    failed = json.loads(capsys.readouterr().out)
    assert failed["status"] == "fail"

    assert main(arguments) == 2
    replay = json.loads(capsys.readouterr().out)
    assert replay["status"] == "failed"
    assert replay["job_id"] == failed["job_id"]
