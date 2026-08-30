"""Import reproducible SQLite -> PostgreSQL para el store shadow HV1-02."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from psycopg import sql
from psycopg.types.json import Jsonb

from mova_fpl.postgres.read_repository import (
    PostgresReadRepository,
    SQLiteReadRepository,
    compare_exact,
    summary as parity_summary,
)
from mova_fpl.postgres.store import (
    PostgresConfig,
    connect,
    publish_status,
    status as postgres_status,
)


class ImportConfig(PostgresConfig, Protocol):
    ops_db: Path
    canonical_db: Path
    trace_db: Path
    artifact_root: Path
    git_sha: str


@dataclass(frozen=True, slots=True)
class TableSpec:
    source_db: str
    source_table: str
    target_table: str
    renames: dict[str, str] = field(default_factory=dict)
    json_columns: frozenset[str] = frozenset()
    bool_columns: frozenset[str] = frozenset()
    include_rowid: bool = False


TABLES = (
    TableSpec("canonical", "player_gameweek", "analytics.player_gameweek",
              bool_columns=frozenset({"was_home"}), include_rowid=True),
    TableSpec("trace", "agent_runs", "agent.legacy_agent_runs",
              renames={"config_json": "config"}, json_columns=frozenset({"config_json"})),
    TableSpec("trace", "gw_decisions", "agent.legacy_gw_decisions",
              json_columns=frozenset({"squad_15", "starters", "bench_order",
                                      "transfers_in", "transfers_out", "auto_subs"})),
    TableSpec("trace", "benchmarks", "agent.legacy_benchmarks"),
    TableSpec("trace", "model_versions", "analytics.legacy_model_versions",
              json_columns=frozenset({"metrics"})),
    TableSpec("trace", "interventions", "agent.legacy_interventions",
              json_columns=frozenset({"payload", "detail"}),
              bool_columns=frozenset({"changed"})),
    TableSpec("ops", "seasons", "game.seasons"),
    TableSpec("ops", "gameweek_cycles", "game.cycles"),
    TableSpec("ops", "runtime_controls", "ops.runtime_controls",
              renames={"value_json": "value"}, json_columns=frozenset({"value_json"})),
    TableSpec("ops", "schema_migrations", "ops.sqlite_schema_migrations"),
    TableSpec("ops", "job_runs", "ops.job_runs",
              renames={"metrics_json": "metrics"}, json_columns=frozenset({"metrics_json"})),
    TableSpec("ops", "job_steps", "ops.job_steps",
              renames={"detail_json": "detail"}, json_columns=frozenset({"detail_json"})),
    TableSpec("ops", "source_snapshots", "raw.source_snapshots",
              renames={"quality_json": "quality"}, json_columns=frozenset({"quality_json"})),
    TableSpec("ops", "team_state_snapshots", "game.team_snapshots",
              renames={"squad_json": "squad", "chips_json": "chips"},
              json_columns=frozenset({"squad_json", "chips_json"})),
    TableSpec("ops", "research_runs", "research.runs",
              renames={"usage_json": "usage", "coverage_json": "coverage"},
              json_columns=frozenset({"usage_json", "coverage_json"})),
    TableSpec("ops", "research_signals", "research.signals",
              renames={"evidence_json": "evidence"},
              json_columns=frozenset({"evidence_json"})),
    TableSpec("ops", "research_documents", "research.documents"),
    TableSpec("ops", "research_conflicts", "research.conflicts",
              renames={"source_urls_json": "source_urls"},
              json_columns=frozenset({"source_urls_json"})),
    TableSpec("ops", "dataset_releases", "analytics.dataset_releases",
              renames={"leakage_audit_json": "leakage_audit"},
              json_columns=frozenset({"leakage_audit_json"})),
    TableSpec("ops", "model_releases", "analytics.model_releases",
              renames={"metrics_json": "metrics"}, json_columns=frozenset({"metrics_json"})),
    TableSpec("ops", "projection_runs", "analytics.projection_runs",
              renames={"model_manifest_json": "model_manifest"},
              json_columns=frozenset({"model_manifest_json"})),
    TableSpec("ops", "intervention_runs", "agent.intervention_runs",
              renames={"payload_json": "payload"}, json_columns=frozenset({"payload_json"})),
    TableSpec("ops", "decision_runs", "agent.decision_runs"),
    TableSpec("ops", "decision_players", "agent.decision_players",
              bool_columns=frozenset({"is_captain", "is_vice_captain"})),
    TableSpec("ops", "cycle_manifests", "agent.cycle_manifests",
              renames={"source_manifest_json": "source_manifest",
                       "analytics_manifest_json": "analytics_manifest",
                       "research_summary_json": "research_summary",
                       "memory_summary_json": "memory_summary"},
              json_columns=frozenset({"source_manifest_json", "analytics_manifest_json",
                                      "research_summary_json", "memory_summary_json"})),
    TableSpec("ops", "decision_envelopes", "agent.decision_envelopes"),
    TableSpec("ops", "decision_candidates", "agent.decision_candidates",
              renames={"decision_json": "decision"},
              json_columns=frozenset({"decision_json"}),
              bool_columns=frozenset({"selected"})),
    TableSpec("ops", "decision_validation_checks", "agent.decision_validation_checks",
              renames={"detail_json": "detail"}, json_columns=frozenset({"detail_json"}),
              bool_columns=frozenset({"passed"})),
    TableSpec("ops", "decision_deliberations", "agent.decision_deliberations",
              renames={"strategist_json": "strategist", "critic_json": "critic",
                       "intervention_json": "intervention", "usage_json": "usage"},
              json_columns=frozenset({"strategist_json", "critic_json",
                                      "intervention_json", "usage_json"})),
    TableSpec("ops", "decision_deliberation_risks",
              "agent.decision_deliberation_risks"),
    TableSpec("ops", "execution_plans", "agent.execution_plans"),
    TableSpec("ops", "execution_preflight_checks", "agent.execution_preflight_checks",
              renames={"detail_json": "detail"}, json_columns=frozenset({"detail_json"}),
              bool_columns=frozenset({"passed"})),
    TableSpec("ops", "execution_attempts", "agent.execution_attempts"),
    TableSpec("ops", "execution_attempt_events", "agent.execution_attempt_events",
              renames={"detail_json": "detail"}, json_columns=frozenset({"detail_json"})),
    TableSpec("ops", "chip_strategy_runs", "agent.chip_strategy_runs",
              renames={"inventory_json": "inventory"},
              json_columns=frozenset({"inventory_json"})),
    TableSpec("ops", "chip_candidates", "agent.chip_candidates"),
    TableSpec("ops", "web_executions", "agent.web_executions"),
    TableSpec("ops", "verification_checks", "agent.verification_checks",
              renames={"expected_json": "expected", "observed_json": "observed"},
              json_columns=frozenset({"expected_json", "observed_json"}),
              bool_columns=frozenset({"passed"})),
    TableSpec("ops", "health_samples", "ops.health_samples",
              renames={"detail_json": "detail"}, json_columns=frozenset({"detail_json"})),
    TableSpec("ops", "audit_events", "ops.audit_events",
              renames={"payload_json": "payload"}, json_columns=frozenset({"payload_json"})),
    TableSpec("ops", "incidents", "ops.incidents",
              renames={"detail_json": "detail"}, json_columns=frozenset({"detail_json"})),
    TableSpec("ops", "outbox_events", "ops.outbox_events",
              renames={"payload_json": "payload"}, json_columns=frozenset({"payload_json"})),
    TableSpec("ops", "gameweek_settlements", "game.gameweek_settlements",
              renames={"auto_subs_json": "auto_subs", "official_json": "official"},
              json_columns=frozenset({"auto_subs_json", "official_json"})),
    TableSpec("ops", "gameweek_reviews", "agent.gw_reviews",
              renames={"metrics_json": "metrics", "findings_json": "findings"},
              json_columns=frozenset({"metrics_json", "findings_json"})),
    TableSpec("ops", "review_player_outcomes", "agent.gw_review_player_outcomes",
              bool_columns=frozenset({"is_captain"})),
    TableSpec("ops", "change_proposals", "agent.change_proposals",
              renames={"evidence_json": "evidence", "acceptance_json": "acceptance"},
              json_columns=frozenset({"evidence_json", "acceptance_json"})),
    TableSpec("ops", "change_proposal_evaluations",
              "agent.change_proposal_evaluations",
              renames={"evidence_json": "evidence"},
              json_columns=frozenset({"evidence_json"})),
    TableSpec("ops", "lessons", "agent.lessons",
              renames={"evidence_json": "evidence"},
              json_columns=frozenset({"evidence_json"})),
    TableSpec("ops", "model_bundle_releases", "agent.model_bundle_releases",
              renames={"candidate_manifest_json": "candidate_manifest",
                       "baseline_manifest_json": "baseline_manifest",
                       "promotion_policy_json": "promotion_policy"},
              json_columns=frozenset({"candidate_manifest_json", "baseline_manifest_json",
                                      "promotion_policy_json"})),
    TableSpec("ops", "model_bundle_release_events",
              "agent.model_bundle_release_events",
              renames={"evidence_json": "evidence"},
              json_columns=frozenset({"evidence_json"})),
    TableSpec("ops", "cost_ledger", "agent.cost_ledger",
              renames={"detail_json": "detail"},
              json_columns=frozenset({"detail_json"}),
              bool_columns=frozenset({"subscription_usage"})),
    TableSpec("ops", "agent_budget_reservations", "agent.budget_reservations",
              renames={"policy_json": "policy"},
              json_columns=frozenset({"policy_json"})),
    TableSpec("ops", "browser_rehearsals", "agent.browser_rehearsals",
              renames={"checks_json": "checks"},
              json_columns=frozenset({"checks_json"}),
              bool_columns=frozenset({"writes_attempted"})),
)

TARGETS = tuple(dict.fromkeys(spec.target_table for spec in TABLES))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _online_backup(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    dst = sqlite3.connect(destination)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    check = sqlite3.connect(f"file:{destination}?mode=ro", uri=True)
    try:
        result = check.execute("pragma quick_check").fetchone()[0]
    finally:
        check.close()
    if result != "ok":
        raise RuntimeError(f"snapshot SQLite inválido: {source.name}: {result}")


def _json_value(value):
    if value is None:
        return None
    if not isinstance(value, str):
        return Jsonb(value)
    try:
        return Jsonb(json.loads(value))
    except json.JSONDecodeError:
        return Jsonb(value)


def _value(spec: TableSpec, column: str, value):
    if column in spec.json_columns:
        return _json_value(value)
    if column in spec.bool_columns:
        return None if value is None else bool(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _source_columns(con: sqlite3.Connection, spec: TableSpec) -> list[str]:
    columns = [str(row[1]) for row in con.execute(
        f"pragma table_info([{spec.source_table}])"
    )]
    if not columns:
        raise RuntimeError(f"tabla SQLite ausente: {spec.source_db}.{spec.source_table}")
    return (["source_row_id"] if spec.include_rowid else []) + columns


def _copy_table(pg, source_path: Path, spec: TableSpec) -> tuple[int, int]:
    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    try:
        columns = _source_columns(source, spec)
        target_columns = [spec.renames.get(column, column) for column in columns]
        select = (f"select rowid as source_row_id,* from [{spec.source_table}]"
                  if spec.include_rowid else f"select * from [{spec.source_table}]")
        schema_name, table_name = spec.target_table.split(".", 1)
        statement = sql.SQL("copy {} ({}) from stdin").format(
            sql.Identifier(schema_name, table_name),
            sql.SQL(",").join(sql.Identifier(column) for column in target_columns),
        )
        source_rows = 0
        with pg.cursor() as cursor, cursor.copy(statement) as copy:
            for row in source.execute(select):
                values = []
                for column in columns:
                    raw = row[column]
                    values.append(_value(spec, column, raw))
                copy.write_row(values)
                source_rows += 1
        target_rows = int(pg.execute(
            sql.SQL("select count(*) as n from {}").format(
                sql.Identifier(schema_name, table_name)
            )
        ).fetchone()["n"])
        return source_rows, target_rows
    finally:
        source.close()


def _publish_sources(config: ImportConfig, import_run_id: str) -> tuple[Path, dict]:
    root = config.artifact_root / "postgres-imports"
    root.mkdir(parents=True, exist_ok=True)
    destination = root / import_run_id
    tmp = root / f".{import_run_id}.{os.getpid()}.tmp"
    tmp.mkdir(parents=False, exist_ok=False)
    source_paths = {
        "ops": config.ops_db,
        "canonical": config.canonical_db,
        "trace": config.trace_db,
    }
    try:
        files = {}
        for name, source in source_paths.items():
            target = tmp / source.name
            _online_backup(source, target)
            files[name] = {
                "name": source.name,
                "bytes": target.stat().st_size,
                "sha256": _sha256(target),
            }
        manifest = {
            "schema": "mova-postgres-import-source-v1",
            "import_run_id": import_run_id,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "git_sha": config.git_sha,
            "files": files,
        }
        manifest_path = tmp / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        manifest["manifest_sha256"] = _sha256(manifest_path)
        tmp.replace(destination)
        return destination, manifest
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def _invariants(sqlite_paths: dict[str, Path], pg) -> dict:
    canonical = sqlite3.connect(f"file:{sqlite_paths['canonical']}?mode=ro", uri=True)
    trace = sqlite3.connect(f"file:{sqlite_paths['trace']}?mode=ro", uri=True)
    try:
        source_canonical = canonical.execute(
            "select count(*),coalesce(sum(total_points),0),coalesce(sum(minutes),0),"
            "min(season),max(season) from player_gameweek"
        ).fetchone()
        source_trace = trace.execute(
            "select count(*),coalesce(sum(total_points),0) from agent_runs"
        ).fetchone()
    finally:
        canonical.close()
        trace.close()
    target_canonical = pg.execute(
        "select count(*) as n,coalesce(sum(total_points),0) as points,"
        "coalesce(sum(minutes),0) as minutes,min(season) as first_season,"
        "max(season) as last_season from analytics.player_gameweek"
    ).fetchone()
    target_trace = pg.execute(
        "select count(*) as n,coalesce(sum(total_points),0) as points "
        "from agent.legacy_agent_runs"
    ).fetchone()
    expected = {
        "canonical": list(source_canonical),
        "trace_agent_runs": list(source_trace),
    }
    observed = {
        "canonical": [target_canonical["n"], target_canonical["points"],
                      target_canonical["minutes"], target_canonical["first_season"],
                      target_canonical["last_season"]],
        "trace_agent_runs": [target_trace["n"], target_trace["points"]],
    }
    return {"status": "pass" if expected == observed else "fail",
            "expected": expected, "observed": observed}


def _content_parity(sqlite_paths: dict[str, Path], pg) -> tuple[list[dict], dict]:
    sqlite_repo = SQLiteReadRepository(sqlite_paths)
    postgres_repo = PostgresReadRepository(pg)
    details = []
    for spec in TABLES:
        if spec.source_db == "canonical":
            continue
        detail = compare_exact(spec, sqlite_repo, postgres_repo)
        details.append({"source_db": spec.source_db,
                        "source_table": spec.source_table, **detail})
    invariants = _invariants(sqlite_paths, pg)
    source_hash = hashlib.sha256(json.dumps(
        invariants["expected"], sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    target_hash = hashlib.sha256(json.dumps(
        invariants["observed"], sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    aggregate = {
        "source_db": "canonical",
        "source_table": "player_gameweek",
        "content_checked": True,
        "content_mode": "aggregate_invariants",
        "content_status": invariants["status"],
        "source_content_sha256": source_hash,
        "target_content_sha256": target_hash,
        "source_rows": invariants["expected"]["canonical"][0],
        "target_rows": invariants["observed"]["canonical"][0],
        "invariants": invariants,
    }
    details.append(aggregate)
    return details, parity_summary(details)


def import_shadow(config: ImportConfig, *, actor: str, reason: str,
                  idempotency_key: str) -> dict:
    if not actor.strip() or not reason.strip() or not idempotency_key.strip():
        raise ValueError("actor, reason e idempotency_key son obligatorios")
    with connect(config, autocommit=True) as pg:
        existing = pg.execute(
            "select import_run_id,status from mova_meta.import_runs where idempotency_key=%s",
            (idempotency_key,),
        ).fetchone()
        if existing:
            return {**existing, "import_status": existing["status"], "status": "reused"}

    import_run_id = f"pgimport_{uuid.uuid4().hex}"
    artifact_path, manifest = _publish_sources(config, import_run_id)
    sqlite_paths = {
        "ops": artifact_path / config.ops_db.name,
        "canonical": artifact_path / config.canonical_db.name,
        "trace": artifact_path / config.trace_db.name,
    }
    files = manifest["files"]

    with connect(config, autocommit=True) as pg:
        pg.execute(
            """
            insert into mova_meta.import_runs(
              import_run_id,idempotency_key,actor,reason,status,git_sha,
              ops_sha256,canonical_sha256,trace_sha256,artifact_path,manifest_sha256
            ) values(%s,%s,%s,%s,'running',%s,%s,%s,%s,%s,%s)
            """,
            (import_run_id, idempotency_key, actor, reason, config.git_sha,
             files["ops"]["sha256"], files["canonical"]["sha256"],
             files["trace"]["sha256"], str(artifact_path), manifest["manifest_sha256"]),
        )
        try:
            with pg.transaction():
                pg.execute("select pg_advisory_xact_lock(%s)", (0x4D4F5642,))
                identifiers = [sql.Identifier(*target.split(".", 1)) for target in TARGETS]
                pg.execute(sql.SQL("truncate {} restart identity cascade").format(
                    sql.SQL(",").join(identifiers)
                ))
                checks = []
                for spec in TABLES:
                    source_rows, target_rows = _copy_table(
                        pg, sqlite_paths[spec.source_db], spec
                    )
                    check_status = "pass" if source_rows == target_rows else "fail"
                    pg.execute(
                        """
                        insert into mova_meta.import_table_checks(
                          import_run_id,source_db,source_table,target_table,
                          source_rows,target_rows,status
                        ) values(%s,%s,%s,%s,%s,%s,%s)
                        """,
                        (import_run_id, spec.source_db, spec.source_table, spec.target_table,
                         source_rows, target_rows, check_status),
                    )
                    checks.append({"source": f"{spec.source_db}.{spec.source_table}",
                                   "target": spec.target_table, "source_rows": source_rows,
                                   "target_rows": target_rows, "status": check_status})
                parity_details, read_parity = _content_parity(sqlite_paths, pg)
                detail_by_source = {
                    (item["source_db"], item["source_table"]): item
                    for item in parity_details
                }
                for check in checks:
                    source_db, source_table = check["source"].split(".", 1)
                    detail = detail_by_source[(source_db, source_table)]
                    check["detail"] = detail
                    if detail["content_status"] != "pass":
                        check["status"] = "fail"
                    pg.execute(
                        "update mova_meta.import_table_checks set status=%s,detail=%s "
                        "where import_run_id=%s and source_db=%s and source_table=%s",
                        (check["status"], Jsonb(detail), import_run_id,
                         source_db, source_table),
                    )
                invariants = next(
                    item["invariants"] for item in parity_details
                    if item["content_mode"] == "aggregate_invariants"
                )
                if read_parity["status"] != "pass" or any(
                    item["status"] != "pass" for item in checks
                ):
                    raise RuntimeError("verificación del import PostgreSQL falló")
            pg.execute(
                "update mova_meta.import_runs set status='completed',finished_at=now() "
                "where import_run_id=%s", (import_run_id,),
            )
        except Exception as exc:
            pg.execute(
                "update mova_meta.import_runs set status='failed',finished_at=now(),"
                "error_detail=%s where import_run_id=%s",
                (str(exc)[:2000], import_run_id),
            )
            try:
                publish_status(config, postgres_status(config))
            except Exception:  # el fallo original conserva precedencia
                pass
            raise
    publish_status(config, postgres_status(config))
    return {"status": "completed", "import_run_id": import_run_id,
            "artifact_path": str(artifact_path), "checks": checks,
            "invariants": invariants, "read_parity": read_parity}


def shadow_sync_identity(config: ImportConfig,
                         *, now: datetime | None = None) -> dict | None:
    con = sqlite3.connect(f"file:{config.ops_db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        cycle = con.execute(
            "select cycle_id,season,gw,deadline_at from gameweek_cycles "
            "order by deadline_at desc limit 1"
        ).fetchone()
    finally:
        con.close()
    if not cycle:
        return None
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    iso_year, iso_week, _ = current.isocalendar()
    return {
        "cycle_id": cycle["cycle_id"],
        "season": cycle["season"],
        "gw": int(cycle["gw"]),
        "deadline_at": cycle["deadline_at"],
        "week_bucket": f"{iso_year}-W{iso_week:02d}",
        "idempotency_key": (
            f"postgres-shadow-sync:{cycle['cycle_id']}:{iso_year}-W{iso_week:02d}"
        ),
    }


def sync_shadow(config: ImportConfig) -> dict:
    """Import semanal por ciclo con identidad determinista para systemd."""
    identity = shadow_sync_identity(config)
    if identity is None:
        return {"status": "skipped", "reason": "cycle_missing"}
    result = import_shadow(
        config,
        actor="scheduler",
        reason="scheduled weekly per-cycle PostgreSQL dual-read parity",
        idempotency_key=identity["idempotency_key"],
    )
    read_parity = result.get("read_parity")
    if not read_parity:
        read_parity = (postgres_status(config).get("read_parity") or {})
    return {
        "status": result.get("status"),
        "import_status": result.get("import_status") or result.get("status"),
        "import_run_id": result.get("import_run_id"),
        "read_parity": read_parity,
        "sync": identity,
    }


def _verify_manifest(artifact_path: Path, expected_sha256: str) -> dict:
    manifest_path = artifact_path / "manifest.json"
    if not manifest_path.is_file():
        return {"status": "fail", "reason": "manifest_missing", "path": str(manifest_path)}
    observed_manifest_sha = _sha256(manifest_path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "fail", "reason": "manifest_invalid",
                "error": type(exc).__name__}
    files = manifest.get("files") if isinstance(manifest, dict) else None
    if observed_manifest_sha != expected_sha256 or not isinstance(files, dict):
        return {"status": "fail", "reason": "manifest_checksum_mismatch",
                "expected": expected_sha256, "observed": observed_manifest_sha}
    file_checks = {}
    for source_db in ("ops", "canonical", "trace"):
        item = files.get(source_db)
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            file_checks[source_db] = {"status": "fail", "reason": "entry_missing"}
            continue
        path = artifact_path / item["name"]
        if not path.is_file():
            file_checks[source_db] = {"status": "fail", "reason": "file_missing"}
            continue
        observed = _sha256(path)
        integrity = None
        try:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                integrity = con.execute("pragma quick_check").fetchone()[0]
            finally:
                con.close()
        except sqlite3.Error:
            integrity = "error"
        passed = observed == item.get("sha256") and integrity == "ok"
        file_checks[source_db] = {
            "status": "pass" if passed else "fail",
            "bytes": path.stat().st_size,
            "sha256": observed,
            "integrity": integrity,
        }
    passed = all(item["status"] == "pass" for item in file_checks.values())
    return {"status": "pass" if passed else "fail", "files": file_checks,
            "manifest_sha256": observed_manifest_sha}


def verify_shadow(config: ImportConfig) -> dict:
    """Revalida el último import contra artefactos y conteos persistidos."""
    with connect(config, autocommit=True) as pg:
        latest = pg.execute(
            "select import_run_id,status,artifact_path,manifest_sha256 "
            "from mova_meta.import_runs where status='completed' "
            "order by finished_at desc limit 1"
        ).fetchone()
        if not latest:
            return {"status": "fail", "reason": "completed_import_missing"}
        stored_checks = pg.execute(
            "select source_db,source_table,target_table,source_rows,target_rows,status,detail "
            "from mova_meta.import_table_checks where import_run_id=%s "
            "order by source_db,source_table",
            (latest["import_run_id"],),
        ).fetchall()
        count_checks = []
        for stored in stored_checks:
            schema_name, table_name = stored["target_table"].split(".", 1)
            observed = int(pg.execute(
                sql.SQL("select count(*) as n from {}").format(
                    sql.Identifier(schema_name, table_name)
                )
            ).fetchone()["n"])
            expected = int(stored["target_rows"])
            count_checks.append({
                "target": stored["target_table"],
                "expected_rows": expected,
                "observed_rows": observed,
                "status": "pass" if observed == expected else "fail",
            })
        artifact_check = _verify_manifest(
            Path(latest["artifact_path"]), latest["manifest_sha256"].strip()
        )
        sqlite_paths = {
            "ops": Path(latest["artifact_path"]) / config.ops_db.name,
            "canonical": Path(latest["artifact_path"]) / config.canonical_db.name,
            "trace": Path(latest["artifact_path"]) / config.trace_db.name,
        }
        observed_details, read_parity = _content_parity(sqlite_paths, pg)
        observed_by_source = {
            (item["source_db"], item["source_table"]): item
            for item in observed_details
        }
        parity_checks = []
        for stored in stored_checks:
            key = (stored["source_db"], stored["source_table"])
            expected = stored.get("detail") or {}
            observed = observed_by_source.get(key) or {}
            passed = (
                expected.get("content_status") == "pass"
                and observed.get("content_status") == "pass"
                and expected.get("source_content_sha256")
                == observed.get("source_content_sha256")
                and expected.get("target_content_sha256")
                == observed.get("target_content_sha256")
            )
            parity_checks.append({
                "source": f"{key[0]}.{key[1]}",
                "mode": observed.get("content_mode"),
                "status": "pass" if passed else "fail",
                "source_content_sha256": observed.get("source_content_sha256"),
                "target_content_sha256": observed.get("target_content_sha256"),
            })
    all_targets_checked = len(count_checks) == len(TABLES)
    passed = (all_targets_checked and artifact_check["status"] == "pass"
              and read_parity["status"] == "pass"
              and len(parity_checks) == len(TABLES)
              and all(item["status"] == "pass" for item in count_checks)
              and all(item["status"] == "pass" for item in parity_checks))
    payload = {
        "status": "pass" if passed else "fail",
        "import_run_id": latest["import_run_id"],
        "writer": "sqlite",
        "postgres_role": "shadow",
        "all_targets_checked": all_targets_checked,
        "artifact": artifact_check,
        "tables": count_checks,
        "read_parity": {**read_parity, "checks": parity_checks},
    }
    publish_status(config, postgres_status(config))
    return payload
