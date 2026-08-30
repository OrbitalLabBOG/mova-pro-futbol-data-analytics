from __future__ import annotations

import json
from pathlib import Path

import pytest

from mova_fpl.ops.cli import parser
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB
from mova_fpl.ops.postgres_roles import run_role_provision
from mova_fpl.postgres.store import verify_role_separation


def _matrix(user: str, *, group: str, writable: bool, read_only: str) -> dict:
    return {
        "current_user": user,
        "expected_membership": True,
        "can_select": True,
        "can_insert": writable,
        "can_update": writable,
        "can_delete": False,
        "can_temp": False,
        "default_read_only": read_only,
    }


def test_role_config_requires_three_distinct_absolute_secrets(tmp_path: Path):
    config = RuntimeConfig(
        postgres_credential_file=tmp_path / "owner",
        postgres_app_credential_file=tmp_path / "app",
        postgres_readonly_credential_file=tmp_path / "readonly",
    )
    config.validate_postgres_roles()
    with pytest.raises(ValueError, match="deben ser distintos"):
        RuntimeConfig(
            postgres_credential_file=tmp_path / "same",
            postgres_app_credential_file=tmp_path / "same",
            postgres_readonly_credential_file=tmp_path / "readonly",
        ).validate_postgres_roles()


def test_role_matrix_fails_closed_on_readonly_write(monkeypatch):
    config = RuntimeConfig()

    def matrix(_config, *, user, expected_group, **_kwargs):
        if expected_group == "mova_app":
            return _matrix(user, group=expected_group, writable=True, read_only="off")
        return _matrix(user, group=expected_group, writable=False, read_only="on")

    monkeypatch.setattr("mova_fpl.postgres.store._permission_matrix", matrix)
    assert verify_role_separation(config)["status"] == "pass"

    def unsafe(_config, *, user, expected_group, **_kwargs):
        item = matrix(_config, user=user, expected_group=expected_group)
        if expected_group == "mova_readonly":
            item["can_update"] = True
        return item

    monkeypatch.setattr("mova_fpl.postgres.store._permission_matrix", unsafe)
    assert verify_role_separation(config)["status"] == "fail"


def test_role_provision_is_audited_idempotent_and_sealed(tmp_path: Path, monkeypatch):
    config = RuntimeConfig(
        ops_db=tmp_path / "db" / "ops.db",
        artifact_root=tmp_path / "artifacts",
        postgres_credential_file=tmp_path / "owner",
        postgres_app_credential_file=tmp_path / "app",
        postgres_readonly_credential_file=tmp_path / "readonly",
    )
    db = OpsDB(config.ops_db, enforce_version=False)
    db.migrate()
    db.upsert_cycle("2026-27", 3, "2026-09-04T17:30:00+00:00", phase="preflight")
    separation = {
        "schema": "mova-postgres-role-separation-v1", "status": "pass",
        "owner_user": "mova_owner", "secrets_distinct": True,
        "app": _matrix("mova_app_runtime", group="mova_app",
                       writable=True, read_only="off") | {"status": "pass"},
        "readonly": _matrix("mova_readonly_runtime", group="mova_readonly",
                            writable=False, read_only="on") | {"status": "pass"},
    }
    monkeypatch.setattr(
        "mova_fpl.ops.postgres_roles.provision_roles", lambda _config: separation
    )

    first = run_role_provision(
        config, db, actor="codex", reason="least privilege",
        idempotency_key="gw03-role-v1",
    )
    reused = run_role_provision(
        config, db, actor="codex", reason="least privilege",
        idempotency_key="gw03-role-v1",
    )

    assert first["status"] == "completed"
    assert reused["status"] == "reused"
    assert reused["job_id"] == first["job_id"]
    artifact = Path(first["artifact_path"])
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["role_separation"]["readonly"]["can_update"] is False
    assert "password" not in artifact.read_text(encoding="utf-8").lower()
    with pytest.raises(ValueError, match="idempotency_key"):
        run_role_provision(
            config, db, actor="codex", reason="different",
            idempotency_key="gw03-role-v1",
        )


def test_role_cli_and_deploy_contracts_are_explicit():
    parsed = parser().parse_args([
        "postgres", "roles", "--actor", "codex", "--reason", "least privilege",
        "--idempotency-key", "gw03-role-v1",
    ])
    assert parsed.postgres_command == "roles"
    root = Path(__file__).parents[1]
    compose = (root / "compose.yaml").read_text(encoding="utf-8")
    bootstrap = (root / "deploy/bin/bootstrap-host.sh").read_text(encoding="utf-8")
    assert "postgres_app_password" in compose
    assert "postgres_readonly_password" in compose
    assert "postgres-app-password postgres-readonly-password" in bootstrap
