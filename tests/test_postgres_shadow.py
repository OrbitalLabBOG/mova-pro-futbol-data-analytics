from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from mova_fpl.ops.cli import parser
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.postgres.importer import TABLES, _json_value, _publish_sources
from mova_fpl.postgres.store import MIGRATIONS, latest_version


def _sqlite(path: Path, statement: str = "create table sample(id integer primary key)") -> None:
    with sqlite3.connect(path) as con:
        con.execute(statement)


def test_postgres_cli_requires_audited_import_fields() -> None:
    parsed = parser().parse_args([
        "postgres", "import", "--actor", "julian", "--reason", "shadow baseline",
        "--idempotency-key", "hv1-02a-baseline",
    ])
    assert parsed.command == "postgres"
    assert parsed.postgres_command == "import"
    assert parsed.idempotency_key == "hv1-02a-baseline"
    with pytest.raises(SystemExit):
        parser().parse_args(["postgres", "import"])


def test_postgres_config_rejects_relative_secret() -> None:
    with pytest.raises(ValueError, match="debe ser absoluto"):
        RuntimeConfig(postgres_credential_file=Path("secret")).validate_postgres()


def test_shadow_mapping_targets_are_unique_and_schema_qualified() -> None:
    source_keys = [(item.source_db, item.source_table) for item in TABLES]
    assert len(source_keys) == len(set(source_keys))
    assert all(target.count(".") == 1 for target in (item.target_table for item in TABLES))
    assert {item.source_db for item in TABLES} == {"ops", "canonical", "trace"}


def test_shadow_migration_is_versioned_and_contains_required_schemas() -> None:
    assert latest_version() == 5
    migration = MIGRATIONS / "001_shadow_store.sql"
    sql = migration.read_text(encoding="utf-8").lower()
    for schema in ("mova_meta", "raw", "analytics", "game", "research", "agent", "ops"):
        assert f"create schema if not exists {schema}" in sql
    assert "revoke create on schema public from public" in sql
    assert "analytics.player_gameweek" in sql
    assert "postgres_role" not in sql


def test_publish_sources_uses_consistent_online_backups(tmp_path: Path) -> None:
    db_root = tmp_path / "db"
    db_root.mkdir()
    ops = db_root / "ops.db"
    canonical = db_root / "canonical.db"
    trace = db_root / "trace.db"
    for path in (ops, canonical, trace):
        _sqlite(path)
    artifacts = tmp_path / "artifacts"
    config = RuntimeConfig(
        ops_db=ops, canonical_db=canonical, trace_db=trace,
        artifact_root=artifacts, postgres_credential_file=tmp_path / "secret",
        git_sha="abc123",
    )

    destination, manifest = _publish_sources(config, "pgimport_test")

    assert destination.name == "pgimport_test"
    manifest_path = destination / "manifest.json"
    assert manifest["manifest_sha256"] == hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    on_disk = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert on_disk["git_sha"] == "abc123"
    for item in on_disk["files"].values():
        snapshot = destination / item["name"]
        assert hashlib.sha256(snapshot.read_bytes()).hexdigest() == item["sha256"]
        with sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True) as con:
            assert con.execute("pragma quick_check").fetchone()[0] == "ok"


def test_json_conversion_preserves_objects_and_wraps_invalid_text() -> None:
    assert _json_value(None) is None
    assert _json_value('{"a": 1}').obj == {"a": 1}
    assert _json_value("plain text").obj == "plain text"
