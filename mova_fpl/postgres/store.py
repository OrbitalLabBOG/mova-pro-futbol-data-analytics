"""Conexión, migraciones y estado del PostgreSQL shadow.

Este módulo no participa todavía en el path de decisión. Su única autoridad es
crear y verificar el store candidato de HV1-02.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

import psycopg
from psycopg.rows import dict_row

from mova_fpl.postgres.read_repository import summary as parity_summary

MIGRATIONS = Path(__file__).with_name("migrations")


class PostgresConfig(Protocol):
    postgres_host: str
    postgres_port: int
    postgres_db: str
    postgres_user: str
    postgres_credential_file: Path

    def validate_postgres(self) -> None: ...


class PostgresStatusConfig(PostgresConfig, Protocol):
    artifact_root: Path


def _password(config: PostgresConfig) -> str:
    try:
        password = config.postgres_credential_file.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError("no se pudo leer el secreto PostgreSQL") from exc
    if not password:
        raise RuntimeError("el secreto PostgreSQL está vacío")
    return password


def connect(config: PostgresConfig, *, autocommit: bool = False):
    config.validate_postgres()
    return psycopg.connect(
        host=config.postgres_host,
        port=config.postgres_port,
        dbname=config.postgres_db,
        user=config.postgres_user,
        password=_password(config),
        connect_timeout=5,
        application_name="mova-shadow",
        autocommit=autocommit,
        row_factory=dict_row,
    )


def _migration_files() -> list[Path]:
    return sorted(MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql"))


def migrate(config: PostgresConfig) -> dict:
    """Aplica migraciones inmutables y bloquea drift de checksum."""
    applied: list[int] = []
    with connect(config) as con:
        con.execute("select pg_advisory_xact_lock(%s)", (0x4D4F5641,))
        con.execute("create schema if not exists mova_meta")
        con.execute(
            """
            create table if not exists mova_meta.schema_migrations (
              version integer primary key,
              name text not null unique,
              checksum char(64) not null check (length(checksum) = 64),
              applied_at timestamptz not null default now()
            )
            """
        )
        existing = {int(row["version"]): row for row in con.execute(
            "select version,name,checksum from mova_meta.schema_migrations"
        )}
        for path in _migration_files():
            version = int(path.name.split("_", 1)[0])
            name = path.stem.split("_", 1)[1]
            sql = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
            if version in existing:
                row = existing[version]
                if row["name"] != name or row["checksum"].strip() != checksum:
                    raise RuntimeError(f"drift en migración PostgreSQL {version}")
                continue
            con.execute(sql, prepare=False)
            con.execute(
                "insert into mova_meta.schema_migrations(version,name,checksum) values(%s,%s,%s)",
                (version, name, checksum),
            )
            applied.append(version)
    return {"status": "completed", "applied": applied, "latest": latest_version()}


def latest_version() -> int:
    files = _migration_files()
    return max((int(path.name.split("_", 1)[0]) for path in files), default=0)


def status(config: PostgresConfig) -> dict:
    with connect(config, autocommit=True) as con:
        server = con.execute(
            "select current_setting('server_version') as version, "
            "current_setting('max_connections')::integer as max_connections"
        ).fetchone()
        migrations = con.execute(
            "select version,name,checksum,applied_at from mova_meta.schema_migrations "
            "order by version"
        ).fetchall()
        schemas = [row["schema_name"] for row in con.execute(
            "select schema_name from information_schema.schemata "
            "where schema_name = any(%s) order by schema_name",
            (["mova_meta", "raw", "analytics", "game", "research", "agent", "ops"],),
        )]
        latest = con.execute(
            "select import_run_id,idempotency_key,actor,reason,status,git_sha,"
            "started_at,finished_at,ops_sha256,canonical_sha256,trace_sha256,"
            "artifact_path,manifest_sha256,error_detail "
            "from mova_meta.import_runs order by started_at desc limit 1"
        ).fetchone()
        table_checks = []
        if latest:
            table_checks = con.execute(
                "select source_db,source_table,target_table,source_rows,target_rows,status,detail "
                "from mova_meta.import_table_checks where import_run_id=%s "
                "order by source_db,source_table",
                (latest["import_run_id"],),
            ).fetchall()
    content_checks = [row.get("detail") or {} for row in table_checks]
    checked = [item for item in content_checks if item.get("content_checked")]
    read_parity = parity_summary(checked) if checked else {
        "schema": "mova-postgres-read-parity-v1", "status": "missing",
        "checked_tables": 0, "exact_tables": 0, "aggregate_tables": 0,
        "failed_tables": 0, "content_sha256": None,
    }
    if table_checks and len(checked) != len(table_checks):
        read_parity = {
            **read_parity, "status": "fail",
            "failed_tables": read_parity["failed_tables"] + len(table_checks) - len(checked),
        }
    return {
        "status": "healthy" if len(schemas) == 7 else "degraded",
        "server_version": server["version"],
        "max_connections": server["max_connections"],
        "schemas": schemas,
        "migrations": migrations,
        "latest_import": latest,
        "table_checks": table_checks,
        "read_parity": read_parity,
        "writer": "sqlite",
        "postgres_role": "shadow",
    }


def prometheus(state: dict) -> str:
    parity = state.get("read_parity") or {}
    parity_status = str(parity.get("status") or "missing")
    finished_at = (state.get("latest_import") or {}).get("finished_at")
    import_age = -1
    if finished_at:
        try:
            parsed = datetime.fromisoformat(str(finished_at).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            import_age = max(0, int((datetime.now(timezone.utc) - parsed).total_seconds()))
        except ValueError:
            pass
    return "\n".join([
        "# HELP mova_postgres_shadow_up PostgreSQL shadow availability.",
        "# TYPE mova_postgres_shadow_up gauge",
        f"mova_postgres_shadow_up {1 if state.get('status') == 'healthy' else 0}",
        "# HELP mova_postgres_read_parity_status Latest imported dual-read parity status.",
        "# TYPE mova_postgres_read_parity_status gauge",
        *[f'mova_postgres_read_parity_status{{status="{name}"}} '
          f'{1 if parity_status == name else 0}'
          for name in ("missing", "pass", "fail")],
        "# HELP mova_postgres_read_parity_tables Tables checked by parity mode.",
        "# TYPE mova_postgres_read_parity_tables gauge",
        f'mova_postgres_read_parity_tables{{mode="exact"}} '
        f'{int(parity.get("exact_tables") or 0)}',
        f'mova_postgres_read_parity_tables{{mode="aggregate"}} '
        f'{int(parity.get("aggregate_tables") or 0)}',
        f'mova_postgres_read_parity_tables{{mode="failed"}} '
        f'{int(parity.get("failed_tables") or 0)}',
        "# HELP mova_postgres_import_age_seconds Age of latest completed shadow import.",
        "# TYPE mova_postgres_import_age_seconds gauge",
        f"mova_postgres_import_age_seconds {import_age}",
        "",
    ])


def _status_path(config: PostgresStatusConfig) -> Path:
    return config.artifact_root / "postgres-shadow-status.json"


def publish_status(config: PostgresStatusConfig, state: dict) -> dict:
    latest = state.get("latest_import") or {}
    payload = {
        "schema": "mova-postgres-shadow-status-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": state.get("status"),
        "server_version": state.get("server_version"),
        "migration_count": len(state.get("migrations") or []),
        "latest_import": {key: latest.get(key) for key in (
            "import_run_id", "status", "git_sha", "started_at", "finished_at"
        )},
        "read_parity": state.get("read_parity"),
        "writer": state.get("writer"),
        "postgres_role": state.get("postgres_role"),
    }
    path = _status_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    tmp.chmod(0o640)
    tmp.replace(path)
    return payload


def read_status(config: PostgresStatusConfig) -> dict:
    path = _status_path(config)
    unavailable = {
        "schema": "mova-postgres-shadow-status-v1",
        "status": "unavailable",
        "read_parity": {"status": "missing"},
        "writer": "sqlite",
        "postgres_role": "unavailable",
    }
    try:
        if not path.is_file() or path.stat().st_size > 256 * 1024:
            return unavailable
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return unavailable
    if not isinstance(payload, dict) or payload.get("schema") != unavailable["schema"]:
        return unavailable
    return payload
