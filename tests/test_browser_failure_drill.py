from __future__ import annotations

import json
from pathlib import Path

from mova_fpl.ops.browser_failure_drill import run
from mova_fpl.ops.cli import main, parser
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB


def test_browser_failure_drill_is_hermetic_and_fail_closed():
    result = run()

    assert result["schema"] == "mova-browser-failure-drill-v1"
    assert result["scenario"] == "dom_drift_ambiguous_save"
    assert result["status"] == "pass"
    assert result["runtime_mutated"] is False
    assert result["fixture_only"] is True
    assert len(result["checks"]) == 11
    assert all(result["checks"].values())


def test_browser_failure_drill_cli_is_audited_idempotent_and_identity_bound(
    tmp_path: Path, monkeypatch, capsys,
):
    config = RuntimeConfig(
        ops_db=tmp_path / "db" / "ops.db", artifact_root=tmp_path / "artifacts",
        git_sha="browser-failure-test", sqlite_min_version="3.40.0",
    )
    config.ops_db.parent.mkdir(parents=True)
    db = OpsDB(config.ops_db, minimum_version=config.sqlite_min_version)
    db.migrate()
    monkeypatch.setattr(RuntimeConfig, "from_env", classmethod(lambda cls: config))
    arguments = [
        "drill", "browser-failure", "--actor", "operator",
        "--reason", "DOM and ambiguous save boundary",
        "--idempotency-key", "browser-failure-1",
    ]

    assert main(arguments) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["status"] == "pass"
    assert db.browser_failure_drill_status()["passed"] == 11

    assert main(arguments) == 0
    replay = json.loads(capsys.readouterr().out)
    assert replay == {
        "schema": "mova-browser-failure-drill-v1", "status": "reused",
        "job_id": first["job_id"],
    }

    conflict = list(arguments)
    conflict[conflict.index("DOM and ambiguous save boundary")] = "different reason"
    assert main(conflict) == 2
    assert json.loads(capsys.readouterr().out)["error_code"] == (
        "idempotency_identity_mismatch"
    )


def test_browser_failure_parser_requires_audit_identity():
    parsed = parser().parse_args([
        "drill", "browser-failure", "--actor", "operator", "--reason", "boundary",
        "--idempotency-key", "browser-failure-1",
    ])
    assert parsed.drill_command == "browser-failure"


def test_failed_browser_failure_drill_never_replays_as_success(
    tmp_path: Path, monkeypatch, capsys,
):
    import mova_fpl.ops.browser_failure_drill as drill_module

    config = RuntimeConfig(
        ops_db=tmp_path / "db" / "ops.db", artifact_root=tmp_path / "artifacts",
        sqlite_min_version="3.40.0",
    )
    config.ops_db.parent.mkdir(parents=True)
    OpsDB(config.ops_db, minimum_version=config.sqlite_min_version).migrate()
    monkeypatch.setattr(RuntimeConfig, "from_env", classmethod(lambda cls: config))
    monkeypatch.setattr(drill_module, "run", lambda: {
        "schema": "mova-browser-failure-drill-v1",
        "scenario": "dom_drift_ambiguous_save", "status": "fail",
        "checks": {"fail_closed": False}, "runtime_mutated": False,
    })
    arguments = [
        "drill", "browser-failure", "--actor", "operator",
        "--reason", "failure path", "--idempotency-key", "browser-failure-failed",
    ]

    assert main(arguments) == 1
    failed = json.loads(capsys.readouterr().out)
    assert failed["status"] == "fail"
    assert main(arguments) == 2
    replay = json.loads(capsys.readouterr().out)
    assert replay["status"] == "failed"
    assert replay["job_id"] == failed["job_id"]
