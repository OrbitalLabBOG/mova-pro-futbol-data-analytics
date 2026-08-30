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
from psycopg import sql
from psycopg.rows import dict_row

from mova_fpl.postgres.read_repository import summary as parity_summary

MIGRATIONS = Path(__file__).with_name("migrations")


class PostgresConfig(Protocol):
    postgres_host: str
    postgres_port: int
    postgres_db: str
    postgres_user: str
    postgres_credential_file: Path
    postgres_app_user: str
    postgres_app_credential_file: Path
    postgres_readonly_user: str
    postgres_readonly_credential_file: Path

    def validate_postgres(self) -> None: ...
    def validate_postgres_roles(self) -> None: ...


class PostgresStatusConfig(PostgresConfig, Protocol):
    artifact_root: Path


def _secret(path: Path, label: str) -> str:
    try:
        password = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(f"no se pudo leer el secreto PostgreSQL {label}") from exc
    if not password:
        raise RuntimeError(f"el secreto PostgreSQL {label} está vacío")
    return password


def connect(config: PostgresConfig, *, autocommit: bool = False):
    config.validate_postgres()
    return psycopg.connect(
        host=config.postgres_host,
        port=config.postgres_port,
        dbname=config.postgres_db,
        user=config.postgres_user,
        password=_secret(config.postgres_credential_file, "owner"),
        connect_timeout=5,
        application_name="mova-shadow",
        autocommit=autocommit,
        row_factory=dict_row,
    )


def _connect_role(config: PostgresConfig, *, user: str, credential_file: Path,
                  application_name: str, autocommit: bool = False):
    config.validate_postgres_roles()
    return psycopg.connect(
        host=config.postgres_host,
        port=config.postgres_port,
        dbname=config.postgres_db,
        user=user,
        password=_secret(credential_file, user),
        connect_timeout=5,
        application_name=application_name,
        autocommit=autocommit,
        row_factory=dict_row,
    )


def connect_readonly(config: PostgresConfig, *, autocommit: bool = False):
    """Open the candidate reader with the dedicated least-privilege identity."""
    return _connect_role(
        config, user=config.postgres_readonly_user,
        credential_file=config.postgres_readonly_credential_file,
        application_name="mova-shadow-readonly", autocommit=autocommit,
    )


def _permission_matrix(config: PostgresConfig, *, user: str,
                       credential_file: Path, expected_group: str) -> dict:
    with _connect_role(
        config, user=user, credential_file=credential_file,
        application_name=f"mova-role-check-{expected_group}", autocommit=True,
    ) as con:
        return con.execute(
            "select current_user as current_user, "
            "pg_has_role(current_user,%s,'member') as expected_membership, "
            "has_table_privilege(current_user,'ops.runtime_controls','select') "
            "as can_select, "
            "has_table_privilege(current_user,'ops.runtime_controls','insert') "
            "as can_insert, "
            "has_table_privilege(current_user,'ops.runtime_controls','update') "
            "as can_update, "
            "has_table_privilege(current_user,'ops.runtime_controls','delete') "
            "as can_delete, "
            "has_database_privilege(current_user,current_database(),'temp') as can_temp, "
            "current_setting('default_transaction_read_only') as default_read_only",
            (expected_group,),
        ).fetchone()


def verify_role_separation(config: PostgresConfig) -> dict:
    """Verify identity, inheritance and effective privileges without mutating data."""
    app = _permission_matrix(
        config, user=config.postgres_app_user,
        credential_file=config.postgres_app_credential_file,
        expected_group="mova_app",
    )
    readonly = _permission_matrix(
        config, user=config.postgres_readonly_user,
        credential_file=config.postgres_readonly_credential_file,
        expected_group="mova_readonly",
    )
    app_pass = (
        app["current_user"] == config.postgres_app_user
        and app["expected_membership"] is True
        and app["can_select"] is True
        and app["can_insert"] is True
        and app["can_update"] is True
        and app["can_delete"] is False
        and app["can_temp"] is False
        and app["default_read_only"] == "off"
    )
    readonly_pass = (
        readonly["current_user"] == config.postgres_readonly_user
        and readonly["expected_membership"] is True
        and readonly["can_select"] is True
        and readonly["can_insert"] is False
        and readonly["can_update"] is False
        and readonly["can_delete"] is False
        and readonly["can_temp"] is False
        and readonly["default_read_only"] == "on"
    )
    return {
        "schema": "mova-postgres-role-separation-v1",
        "status": "pass" if app_pass and readonly_pass else "fail",
        "owner_user": config.postgres_user,
        "app": {**app, "status": "pass" if app_pass else "fail"},
        "readonly": {**readonly, "status": "pass" if readonly_pass else "fail"},
        "secrets_distinct": len({
            str(config.postgres_credential_file),
            str(config.postgres_app_credential_file),
            str(config.postgres_readonly_credential_file),
        }) == 3,
    }


def provision_roles(config: PostgresConfig) -> dict:
    """Rotate dedicated LOGIN passwords and prove their least privileges."""
    config.validate_postgres_roles()
    app_password = _secret(config.postgres_app_credential_file, "app")
    readonly_password = _secret(config.postgres_readonly_credential_file, "readonly")
    with connect(config, autocommit=True) as con:
        con.execute(
            sql.SQL("alter role {} password %s").format(
                sql.Identifier(config.postgres_app_user)
            ),
            (app_password,),
        )
        con.execute(
            sql.SQL("alter role {} password %s").format(
                sql.Identifier(config.postgres_readonly_user)
            ),
            (readonly_password,),
        )
    return verify_role_separation(config)


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
        import_history = con.execute(
            "select count(*) filter (where status='completed') as completed_imports, "
            "count(distinct (ops_sha256,canonical_sha256,trace_sha256)) "
            "filter (where status='completed') as distinct_source_snapshots, "
            "count(distinct substring(idempotency_key from "
            "'([0-9]{4}-[0-9]{2}-gw[0-9]{2})')) "
            "filter (where status='completed' and idempotency_key ~ "
            "'[0-9]{4}-[0-9]{2}-gw[0-9]{2}') as distinct_gameweek_cycles, "
            "min(finished_at) filter (where status='completed') as first_completed_at, "
            "max(finished_at) filter (where status='completed') as last_completed_at "
            "from mova_meta.import_runs"
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
    role_separation = verify_role_separation(config)
    healthy = len(schemas) == 7 and role_separation["status"] == "pass"
    return {
        "status": "healthy" if healthy else "degraded",
        "server_version": server["version"],
        "max_connections": server["max_connections"],
        "schemas": schemas,
        "migrations": migrations,
        "latest_import": latest,
        "import_history": import_history,
        "table_checks": table_checks,
        "read_parity": read_parity,
        "writer": "sqlite",
        "postgres_role": "shadow",
        "role_separation": role_separation,
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
    role_status = str((state.get("role_separation") or {}).get("status") or "missing")
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
        "# HELP mova_postgres_distinct_source_snapshots Distinct completed source snapshots.",
        "# TYPE mova_postgres_distinct_source_snapshots gauge",
        f"mova_postgres_distinct_source_snapshots "
        f"{int((state.get('import_history') or {}).get('distinct_source_snapshots') or 0)}",
        "# HELP mova_postgres_distinct_gameweek_cycles Gameweek cycles with completed imports.",
        "# TYPE mova_postgres_distinct_gameweek_cycles gauge",
        f"mova_postgres_distinct_gameweek_cycles "
        f"{int((state.get('import_history') or {}).get('distinct_gameweek_cycles') or 0)}",
        "# HELP mova_postgres_role_separation_status Dedicated runtime role verification.",
        "# TYPE mova_postgres_role_separation_status gauge",
        *[f'mova_postgres_role_separation_status{{status="{name}"}} '
          f'{1 if role_status == name else 0}'
          for name in ("missing", "pass", "fail")],
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
        "import_history": {key: (state.get("import_history") or {}).get(key) for key in (
            "completed_imports", "distinct_source_snapshots", "distinct_gameweek_cycles",
            "first_completed_at", "last_completed_at"
        )},
        "read_parity": state.get("read_parity"),
        "writer": state.get("writer"),
        "postgres_role": state.get("postgres_role"),
        "role_separation": state.get("role_separation"),
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
