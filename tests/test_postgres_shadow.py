from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mova_fpl.ops.cli import parser
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.postgres.importer import (
    TABLES,
    TableSpec,
    _json_value,
    _publish_sources,
    shadow_sync_identity,
)
from mova_fpl.postgres.read_repository import (
    PostgresReadRepository,
    SQLiteReadRepository,
    compare_exact,
    summary,
)
from mova_fpl.postgres.store import (
    MIGRATIONS,
    latest_version,
    prometheus,
    publish_status,
    read_status,
)


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
    assert parser().parse_args(["postgres", "sync"]).postgres_command == "sync"


def test_postgres_config_rejects_relative_secret() -> None:
    with pytest.raises(ValueError, match="debe ser absoluto"):
        RuntimeConfig(postgres_credential_file=Path("secret")).validate_postgres()


def test_shadow_mapping_targets_are_unique_and_schema_qualified() -> None:
    source_keys = [(item.source_db, item.source_table) for item in TABLES]
    assert len(source_keys) == len(set(source_keys))
    assert all(target.count(".") == 1 for target in (item.target_table for item in TABLES))
    assert {item.source_db for item in TABLES} == {"ops", "canonical", "trace"}


def test_shadow_migration_is_versioned_and_contains_required_schemas() -> None:
    assert latest_version() == 16
    migration = MIGRATIONS / "001_shadow_store.sql"
    sql = migration.read_text(encoding="utf-8").lower()
    for schema in ("mova_meta", "raw", "analytics", "game", "research", "agent", "ops"):
        assert f"create schema if not exists {schema}" in sql
    assert "revoke create on schema public from public" in sql
    assert "analytics.player_gameweek" in sql
    assert "postgres_role" not in sql
    review_sql = (MIGRATIONS / "006_gameweek_review.sql").read_text(encoding="utf-8").lower()
    assert "game.gameweek_settlements" in review_sql
    assert "agent.gw_reviews" in review_sql
    assert "agent.change_proposals" in review_sql
    envelope_sql = (MIGRATIONS / "008_decision_envelopes.sql").read_text(
        encoding="utf-8"
    ).lower()
    assert "agent.cycle_manifests" in envelope_sql
    assert "agent.decision_envelopes" in envelope_sql
    assert "agent.decision_validation_checks" in envelope_sql
    execution_sql = (MIGRATIONS / "010_execution_plans.sql").read_text(
        encoding="utf-8"
    ).lower()
    assert "agent.execution_plans" in execution_sql
    assert "agent.execution_preflight_checks" in execution_sql
    provenance_sql = (MIGRATIONS / "011_execution_plan_job_provenance.sql").read_text(
        encoding="utf-8"
    ).lower()
    assert "job_id text references ops.job_runs" in provenance_sql
    attempts_sql = (MIGRATIONS / "012_execution_attempts.sql").read_text(
        encoding="utf-8"
    ).lower()
    assert "agent.execution_attempts" in attempts_sql
    assert "agent.execution_attempt_events" in attempts_sql
    improvement_sql = (MIGRATIONS / "013_continuous_improvement_gate.sql").read_text(
        encoding="utf-8"
    ).lower()
    assert "agent.change_proposal_evaluations" in improvement_sql
    assert "agent.lessons" in improvement_sql
    release_sql = (MIGRATIONS / "015_model_bundle_release_gate.sql").read_text(
        encoding="utf-8"
    ).lower()
    assert "agent.model_bundle_releases" in release_sql
    assert "agent.model_bundle_release_events" in release_sql
    memory_sql = (MIGRATIONS / "016_strategic_memory_snapshots.sql").read_text(
        encoding="utf-8"
    ).lower()
    assert "alter table agent.cycle_manifests" in memory_sql
    assert "memory_summary jsonb" in memory_sql
    cycle_mapping = next(item for item in TABLES if item.source_table == "cycle_manifests")
    assert cycle_mapping.renames["memory_summary_json"] == "memory_summary"
    assert "memory_summary_json" in cycle_mapping.json_columns


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


def test_dual_read_repository_normalizes_types_and_detects_value_drift(
    tmp_path: Path,
) -> None:
    ops = tmp_path / "ops.db"
    with sqlite3.connect(ops) as con:
        con.execute(
            "create table sample(id integer primary key,observed_at text,payload_json text,"
            "enabled integer)"
        )
        con.execute(
            "insert into sample values(1,'2026-08-30T19:00:00Z','{\"b\":2,\"a\":1}',1)"
        )
    mapping = TableSpec(
        "ops", "sample", "ops.sample",
        renames={"payload_json": "payload"},
        json_columns=frozenset({"payload_json"}),
        bool_columns=frozenset({"enabled"}),
    )

    class Result:
        def __init__(self, rows):
            self.rows = rows

        def fetchall(self):
            return self.rows

        def fetchone(self):
            return self.rows[0] if self.rows else None

    class FakePG:
        def __init__(self, rows):
            self.rows = rows

        def execute(self, statement, _params=None):
            if isinstance(statement, str):
                return Result([{"present": 1}])
            return Result(self.rows)

    equivalent = [{
        "enabled": True,
        "id": 1,
        "observed_at": datetime(2026, 8, 30, 19, tzinfo=timezone.utc),
        "payload": {"a": 1, "b": 2},
    }]
    sqlite_repo = SQLiteReadRepository({"ops": ops})
    passed = compare_exact(
        mapping, sqlite_repo, PostgresReadRepository(FakePG(equivalent))
    )

    assert passed["content_status"] == "pass"
    assert passed["source_content_sha256"] == passed["target_content_sha256"]
    report = summary([passed])
    assert report["status"] == "pass"
    assert report["exact_tables"] == 1

    drifted = [dict(equivalent[0], enabled=False)]
    failed = compare_exact(
        mapping, sqlite_repo, PostgresReadRepository(FakePG(drifted))
    )
    assert failed["content_status"] == "fail"
    assert summary([failed])["failed_tables"] == 1


def test_postgres_parity_metrics_are_explicit() -> None:
    metrics = prometheus({
        "status": "healthy",
        "read_parity": {
            "status": "pass", "exact_tables": 48,
            "aggregate_tables": 1, "failed_tables": 0,
        },
    })
    assert "mova_postgres_shadow_up 1" in metrics
    assert 'mova_postgres_read_parity_status{status="pass"} 1' in metrics
    assert 'mova_postgres_read_parity_tables{mode="exact"} 48' in metrics
    assert 'mova_postgres_read_parity_tables{mode="aggregate"} 1' in metrics
    assert "mova_postgres_import_age_seconds -1" in metrics


def test_postgres_status_artifact_is_sanitized_and_readable(tmp_path: Path) -> None:
    config = RuntimeConfig(artifact_root=tmp_path / "artifacts")
    payload = publish_status(config, {
        "status": "healthy",
        "server_version": "17.11",
        "migrations": [{"version": 1}],
        "latest_import": {
            "import_run_id": "pgimport_test", "status": "completed",
            "git_sha": "abc123", "started_at": "2026-08-30T19:00:00Z",
            "finished_at": "2026-08-30T19:00:20Z",
            "actor": "must-not-leak", "reason": "must-not-leak",
            "artifact_path": "/private/path",
        },
        "read_parity": {"status": "pass", "checked_tables": 49},
        "writer": "sqlite",
        "postgres_role": "shadow",
    })

    assert payload["latest_import"] == {
        "import_run_id": "pgimport_test", "status": "completed",
        "git_sha": "abc123", "started_at": "2026-08-30T19:00:00Z",
        "finished_at": "2026-08-30T19:00:20Z",
    }
    assert read_status(config) == payload
    raw = (config.artifact_root / "postgres-shadow-status.json").read_text()
    assert "must-not-leak" not in raw
    assert "/private/path" not in raw


def test_scheduled_sync_identity_is_stable_per_cycle_and_iso_week(tmp_path: Path) -> None:
    ops = tmp_path / "ops.db"
    with sqlite3.connect(ops) as con:
        con.execute(
            "create table gameweek_cycles(cycle_id text,season text,gw integer,"
            "deadline_at text)"
        )
        con.execute(
            "insert into gameweek_cycles values('2026-27-gw03','2026-27',3,"
            "'2026-09-04T17:30:00Z')"
        )
    config = RuntimeConfig(ops_db=ops)

    identity = shadow_sync_identity(
        config, now=datetime(2026, 8, 30, 20, tzinfo=timezone.utc)
    )

    assert identity == {
        "cycle_id": "2026-27-gw03", "season": "2026-27", "gw": 3,
        "deadline_at": "2026-09-04T17:30:00Z", "week_bucket": "2026-W35",
        "idempotency_key": "postgres-shadow-sync:2026-27-gw03:2026-W35",
    }


def test_postgres_sync_timer_is_persistent_and_locked() -> None:
    root = Path(__file__).parents[1]
    timer = (root / "deploy/systemd/mova-fpl-postgres-sync.timer").read_text()
    service = (root / "deploy/systemd/mova-fpl-postgres-sync.service").read_text()
    assert "Persistent=true" in timer
    assert "RandomizedDelaySec=300s" in timer
    assert "/run/lock/mova-fpl-worker.lock" in service
    assert "/usr/local/bin/mova postgres sync" in service
