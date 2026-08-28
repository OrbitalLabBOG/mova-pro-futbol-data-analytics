"""Contrato estable de observabilidad para operadores humanos y agentes."""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from mova_fpl.data.sources import fetch_bootstrap
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB
from mova_fpl.ops.schedule import (
    phase_for,
    private_state_cadence_seconds,
    public_state_cadence_seconds,
)
from mova_fpl.ops.schema import MIGRATIONS

SCHEMA_VERSION = "1.0"
COMMAND_SCHEMA = "mova-fpl-operator-v1"
MAX_HOST_PROBE_BYTES = 256 * 1024
TICK_MAX_AGE_SECONDS = 20 * 60


def _utcnow(now: datetime | None = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    return current if current.tzinfo else current.replace(tzinfo=timezone.utc)


def _iso(now: datetime) -> str:
    return now.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse_time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _age(value: object, now: datetime) -> int | None:
    observed = _parse_time(value)
    if observed is None:
        return None
    return max(0, int((now - observed).total_seconds()))


def _json(value: object, fallback):
    try:
        return json.loads(value) if isinstance(value, str) else value
    except (TypeError, json.JSONDecodeError):
        return fallback


def _latest_rows(con: sqlite3.Connection, table: str, group: str, order: str) -> list[dict]:
    rows = con.execute(
        f"SELECT t.* FROM {table} t WHERE rowid=(SELECT x.rowid FROM {table} x "
        f"WHERE x.{group}=t.{group} ORDER BY x.{order} DESC, x.rowid DESC LIMIT 1) "
        f"ORDER BY t.{group}"
    ).fetchall()
    return [dict(row) for row in rows]


def _database_snapshot(db: OpsDB) -> dict:
    with db.connect(readonly=True) as con:
        cycle = con.execute(
            "SELECT * FROM gameweek_cycles ORDER BY deadline_at DESC LIMIT 1"
        ).fetchone()
        latest_tick = con.execute(
            "SELECT * FROM job_runs WHERE job_type='tick' ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        team = con.execute(
            "SELECT * FROM team_state_snapshots ORDER BY observed_at DESC LIMIT 1"
        ).fetchone()
        decision = con.execute(
            "SELECT * FROM decision_runs ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        envelope = con.execute(
            "SELECT * FROM decision_envelopes ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        projection = con.execute(
            "SELECT * FROM projection_runs ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        execution = con.execute(
            "SELECT * FROM web_executions ORDER BY COALESCE(finished_at,started_at) DESC LIMIT 1"
        ).fetchone()
        health = con.execute(
            "SELECT * FROM health_samples ORDER BY observed_at DESC LIMIT 1"
        ).fetchone()
        migrations = [int(row[0]) for row in con.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        )]
        incidents = [dict(row) for row in con.execute(
            "SELECT incident_id,severity,status,title,opened_at FROM incidents "
            "WHERE status!='resolved' ORDER BY severity,opened_at"
        ).fetchall()]
        failed_jobs = [dict(row) for row in con.execute(
            "SELECT job_id,job_type,status,started_at,error_code FROM job_runs "
            "WHERE status='failed' ORDER BY started_at DESC LIMIT 20"
        ).fetchall()]
        pending = int(con.execute(
            "SELECT COUNT(*) FROM outbox_events WHERE status IN ('pending','sending')"
        ).fetchone()[0])
        sources = _latest_rows(con, "source_snapshots", "source_name", "captured_at")
        datasets = _latest_rows(con, "dataset_releases", "dataset_name", "created_at")
        models = _latest_rows(con, "model_releases", "model_name", "created_at")
        cycle_id = str(cycle["cycle_id"]) if cycle else None
        research = {"signals": 0, "conflicts": 0}
        strategic = {"manifest": None, "research_runs": []}
        if cycle_id:
            row = con.execute(
                "SELECT COUNT(*) AS signals, "
                "SUM(CASE WHEN conflict_status='unresolved' THEN 1 ELSE 0 END) AS conflicts "
                "FROM research_signals WHERE cycle_id=?", (cycle_id,),
            ).fetchone()
            research = {"signals": int(row["signals"] or 0),
                        "conflicts": int(row["conflicts"] or 0)}
            manifest = con.execute(
                "SELECT manifest_id,revision,as_of_at,phase,team_state_id,plan_id,"
                "content_sha256,artifact_path FROM cycle_manifests WHERE cycle_id=? "
                "ORDER BY revision DESC LIMIT 1", (cycle_id,),
            ).fetchone()
            runs = con.execute(
                "SELECT research_run_id,provider,status,queued_at,finished_at,imported_at,"
                "error_code FROM research_runs WHERE cycle_id=? "
                "ORDER BY queued_at DESC LIMIT 10", (cycle_id,),
            ).fetchall()
            strategic = {
                "manifest": dict(manifest) if manifest else None,
                "research_runs": [dict(item) for item in runs],
            }
    return {
        "cycle": dict(cycle) if cycle else None,
        "latest_tick": dict(latest_tick) if latest_tick else None,
        "team_state": dict(team) if team else None,
        "decision": dict(decision) if decision else None,
        "decision_envelope": dict(envelope) if envelope else None,
        "projection": dict(projection) if projection else None,
        "execution": dict(execution) if execution else None,
        "health": dict(health) if health else None,
        "migrations": migrations,
        "incidents": incidents,
        "failed_jobs": failed_jobs,
        "outbox_pending": pending,
        "sources": sources,
        "datasets": datasets,
        "models": models,
        "research": research,
        "strategic": strategic,
        "controls": db.controls(),
    }


def _load_host_probe(path: Path, now: datetime) -> dict:
    unavailable = {"available": False, "reason": "host_probe_unavailable"}
    try:
        if not path.is_file() or path.stat().st_size > MAX_HOST_PROBE_BYTES:
            return unavailable
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema") != "mova-host-probe-v1":
            return {"available": False, "reason": "host_probe_invalid"}
        return {**payload, "available": True,
                "age_seconds": _age(payload.get("observed_at"), now)}
    except (OSError, json.JSONDecodeError):
        return unavailable


def _controls(raw: dict, config: RuntimeConfig) -> dict:
    defaults = {
        "mode": config.mode,
        "action_level": config.action_level,
        "compliance_gate": config.compliance_gate,
        "kill_switch": True,
        "browser_writes": config.enable_browser_writes,
    }
    return {key: (raw.get(key) or {}).get("value", default)
            for key, default in defaults.items()}


def build_status(config: RuntimeConfig, db: OpsDB, *, now: datetime | None = None) -> dict:
    """Construye el estado operativo sin mutar DB, fuentes o controles."""
    current = _utcnow(now)
    state = _database_snapshot(db)
    cycle = state["cycle"] or {}
    deadline = cycle.get("deadline_at")
    effective_phase = phase_for(str(deadline), current) if deadline else None
    deadline_at = _parse_time(deadline)
    deadline_seconds = int((deadline_at - current).total_seconds()) if deadline_at else None

    team = state["team_state"] or {}
    team_age = _age(team.get("observed_at"), current)
    team_max_age = (
        min(config.private_state_max_age_seconds,
            private_state_cadence_seconds(str(deadline), current)) if deadline else None
    )
    squad = _json(team.get("squad_json"), []) or []
    chips = _json(team.get("chips_json"), []) or []

    sources = []
    source_max_age = public_state_cadence_seconds(str(deadline), current) if deadline else None
    for source in state["sources"]:
        source_age = _age(source["captured_at"], current)
        quality = _json(source.get("quality_json"), {}) or {}
        is_live_source = source["source_name"] == "fpl_official"
        fresh = (
            source_age is not None and source_max_age is not None
            and source_age <= source_max_age
        ) if is_live_source else source["quality_status"] == "valid"
        sources.append({
            "name": source["source_name"],
            "captured_at": source["captured_at"],
            "age_seconds": source_age,
            "max_age_seconds": source_max_age if is_live_source else None,
            "fresh": fresh,
            "quality": source["quality_status"],
            "artifact_path": source["artifact_path"],
            "manifest_sha256": source["manifest_sha256"],
            "event_context": quality.get("event_context"),
        })

    event_context = next((source.get("event_context") for source in sources
                          if source.get("event_context")), {}) or {}

    controls = _controls(state["controls"], config)
    tick = state["latest_tick"] or {}
    tick_age = _age(tick.get("finished_at") or tick.get("started_at"), current)
    active_failures = []
    for item in state["failed_jobs"]:
        failure_age = _age(item.get("started_at"), current)
        if failure_age is not None and failure_age <= 86400:
            active_failures.append(item)
    host = _load_host_probe(config.host_probe_path, current)
    model_root = config.artifact_root / "models"
    model_artifacts = []
    if model_root.is_dir():
        for path in sorted(model_root.rglob("*.joblib")):
            stat = path.stat()
            model_artifacts.append({
                "name": path.parent.name,
                "path": str(path),
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(
                    stat.st_mtime, timezone.utc
                ).isoformat(timespec="seconds"),
            })

    data_service = {"status": "unavailable", "sources": [], "counts": {},
                    "latest_runs": []}
    try:
        if config.postgres_credential_file.is_file():
            from mova_fpl.ops.collector.store import CollectorStore
            data_service = CollectorStore(config).status()
        else:
            from mova_fpl.ops.collector.store import read_status
            data_service = read_status(config)
    except Exception as exc:  # noqa: BLE001 - status debe seguir disponible
        data_service = {"status": "unavailable", "sources": [], "counts": {},
                        "latest_runs": [], "error": type(exc).__name__}
    analytics_service = {"status": "unavailable", "latest_scorecards": [],
                         "latest_projection_batches": []}
    try:
        if config.postgres_credential_file.is_file():
            from mova_fpl.ops.analytics_store import AnalyticsStore
            analytics_service = AnalyticsStore(config).status()
        else:
            from mova_fpl.ops.analytics_store import read_status as read_analytics_status
            analytics_service = read_analytics_status(config)
    except Exception as exc:  # noqa: BLE001 - status consolidado sigue disponible
        analytics_service = {"status": "unavailable", "latest_scorecards": [],
                             "latest_projection_batches": [], "error": type(exc).__name__}

    severity = "healthy"
    reasons: list[str] = []
    if any(item["severity"] in {"P0", "P1"} for item in state["incidents"]):
        severity, reasons = "critical", ["open_p0_or_p1_incident"]
    else:
        if not tick or tick.get("status") not in {"completed", "degraded"}:
            reasons.append("latest_tick_not_successful")
        elif tick_age is None or tick_age > TICK_MAX_AGE_SECONDS:
            reasons.append("latest_tick_stale")
        if team_age is None:
            reasons.append("team_state_missing")
        elif team_max_age is not None and team_age > team_max_age:
            reasons.append("team_state_stale")
        if not sources:
            reasons.append("public_source_missing")
        elif any(not source["fresh"] or source["quality"] != "valid" for source in sources):
            reasons.append("public_source_stale_or_invalid")
        if active_failures:
            reasons.append("failed_jobs_last_24h")
        if data_service.get("status") == "degraded":
            reasons.append("data_service_degraded")
        if analytics_service.get("status") == "alert":
            reasons.append("model_drift_alert")
        if reasons:
            severity = "degraded"

    return {
        "schema": COMMAND_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "command": "status",
        "generated_at": _iso(current),
        "overall_status": severity,
        "status_reasons": reasons,
        "runtime": {
            "season": config.season,
            "team_id": config.team_id,
            "git_sha": config.git_sha,
            "sqlite_version": db.sqlite_version,
            "controls": controls,
        },
        "gameweek": {
            "cycle_id": cycle.get("cycle_id"),
            "gw": cycle.get("gw"),
            "deadline_at": deadline,
            "seconds_to_deadline": deadline_seconds,
            "phase": effective_phase,
            "recorded_phase": cycle.get("phase"),
            "readiness": "preliminary" if event_context.get("preliminary") else "ready",
            "readiness_reasons": event_context.get("readiness_reasons") or [],
            "current_gw": event_context.get("current_gw"),
            "prior_gw": event_context.get("prior_gw"),
            "prior_gameweek_settled": event_context.get("prior_settled"),
            "prior_unstarted_fixtures": event_context.get("prior_unstarted_fixtures"),
        },
        "data": {
            "sources": sources,
            "service": data_service,
            "team_state": {
                "observed_at": team.get("observed_at"),
                "age_seconds": team_age,
                "max_age_seconds": team_max_age,
                "quality": team.get("quality_status"),
                "source": team.get("source_name"),
                "squad_size": len(squad),
                "free_transfers": team.get("free_transfers"),
                "bank_tenths": team.get("bank_tenths"),
                "chips": chips,
                "fingerprint": team.get("fingerprint"),
            },
            "datasets": [{key: row.get(key) for key in (
                "dataset_id", "dataset_name", "version", "as_of_at", "row_count",
                "artifact_sha256", "created_at"
            )} for row in state["datasets"]],
        },
        "models": {
            "registered": [{key: row.get(key) for key in (
                "model_release_id", "model_name", "version", "artifact_sha256", "status",
                "created_at"
            )} for row in state["models"]],
            "artifacts": model_artifacts,
        },
        "analytics": analytics_service,
        "research": state["research"],
        "strategy": state["strategic"],
        "decision": ({key: state["decision"].get(key) for key in (
            "decision_id", "cycle_id", "revision", "mode", "policy_version", "status",
            "expected_points", "chip", "fingerprint", "manifest_sha256", "created_at"
        )} if state["decision"] else None),
        "decision_envelope": ({key: state["decision_envelope"].get(key) for key in (
            "envelope_id", "decision_id", "cycle_id", "manifest_id", "schema_version",
            "policy_version", "status", "selected_candidate_key", "content_sha256",
            "artifact_sha256", "created_at"
        )} if state["decision_envelope"] else None),
        "projection": ({key: state["projection"].get(key) for key in (
            "projection_id", "cycle_id", "input_manifest_sha256", "artifact_sha256",
            "player_count", "created_at"
        )} if state["projection"] else None),
        "execution": ({key: state["execution"].get(key) for key in (
            "execution_id", "decision_id", "action_level", "envelope_sha256", "status",
            "started_at", "finished_at", "evidence_sha256", "error_code"
        )} if state["execution"] else None),
        "operations": {
            "latest_tick": ({key: tick.get(key) for key in (
                "job_id", "cycle_id", "status", "started_at", "finished_at", "output_sha256",
                "error_code"
            )} if tick else None),
            "latest_tick_age_seconds": tick_age,
            "latest_health": ({key: state["health"].get(key) for key in (
                "sample_id", "observed_at", "service", "status", "memory_available_bytes",
                "disk_free_bytes", "load_1m", "sqlite_version"
            )} if state["health"] else None),
            "open_incidents": state["incidents"],
            "failed_jobs_last_24h": active_failures,
            "outbox_pending": state["outbox_pending"],
            "schema_migrations": state["migrations"],
        },
        "host": host,
    }


def _check(name: str, status: str, summary: str, *, required: bool = True,
           detail: dict | None = None) -> dict:
    return {"name": name, "status": status, "required": required,
            "summary": summary, "detail": detail or {}}


def _sqlite_check(path: Path, required_tables: tuple[str, ...]) -> dict:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    try:
        integrity = str(con.execute("PRAGMA quick_check").fetchone()[0])
        tables = {str(row[0]) for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        missing = sorted(set(required_tables) - tables)
        counts = {name: int(con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0])
                  for name in required_tables if name in tables}
        return {"integrity": integrity, "missing_tables": missing, "row_counts": counts}
    finally:
        con.close()


def _memory_available_bytes() -> int:
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    return 0


def build_doctor(config: RuntimeConfig, db: OpsDB, *, now: datetime | None = None,
                 network: bool = True,
                 bootstrap_fetcher: Callable[..., bytes] = fetch_bootstrap) -> dict:
    """Ejecuta diagnóstico acotado; no migra ni modifica estado operativo."""
    current = _utcnow(now)
    checks: list[dict] = []
    try:
        config.validate()
        checks.append(_check("configuration", "PASS", "runtime configuration is valid"))
    except Exception as exc:  # noqa: BLE001 - el doctor debe reportar, no abortar
        checks.append(_check("configuration", "FAIL", "runtime configuration is invalid",
                             detail={"error": type(exc).__name__, "message": str(exc)}))

    status = None
    try:
        integrity = db.quick_check()
        status = build_status(config, db, now=current)
        checks.append(_check("ops_database", "PASS", "ops database is readable and consistent",
                             detail={"integrity": integrity, "path": str(config.ops_db)}))
    except Exception as exc:  # noqa: BLE001
        checks.append(_check("ops_database", "FAIL", "ops database is unavailable",
                             detail={"error": type(exc).__name__, "message": str(exc)}))

    if status:
        versions = status["operations"]["schema_migrations"]
        expected = MIGRATIONS[-1][0]
        migration_status = "PASS" if versions and versions[-1] == expected else "FAIL"
        checks.append(_check("ops_schema", migration_status,
                             "schema is current" if migration_status == "PASS" else "schema drift",
                             detail={"applied": versions, "expected_latest": expected}))
        tick = status["operations"]["latest_tick"] or {}
        tick_age = status["operations"]["latest_tick_age_seconds"]
        tick_ok = tick.get("status") in {"completed", "degraded"} \
            and tick_age is not None and tick_age <= TICK_MAX_AGE_SECONDS
        checks.append(_check("scheduler_heartbeat", "PASS" if tick_ok else "FAIL",
                             "worker heartbeat is fresh" if tick_ok else "worker heartbeat is stale",
                             detail={"status": tick.get("status"), "age_seconds": tick_age,
                                     "max_age_seconds": TICK_MAX_AGE_SECONDS}))
        team = status["data"]["team_state"]
        team_ok = team["age_seconds"] is not None and team["max_age_seconds"] is not None \
            and team["age_seconds"] <= team["max_age_seconds"] and team["squad_size"] == 15 \
            and team["quality"] == "valid"
        checks.append(_check("private_team_state", "PASS" if team_ok else "WARN",
                             "private team state is current" if team_ok else "private team state needs refresh",
                             required=False, detail={key: team[key] for key in (
                                 "observed_at", "age_seconds", "max_age_seconds", "quality",
                                 "squad_size", "free_transfers", "bank_tenths"
                             )}))

    for name, path, tables in (
        ("canonical_database", config.canonical_db, ("player_gameweek",)),
        ("trace_database", config.trace_db,
         ("agent_runs", "gw_decisions", "model_versions", "interventions")),
    ):
        try:
            result = _sqlite_check(path, tables)
            populated = name != "canonical_database" or result["row_counts"].get(
                "player_gameweek", 0
            ) > 0
            ok = result["integrity"] == "ok" and not result["missing_tables"] and populated
            checks.append(_check(name, "PASS" if ok else "FAIL",
                                 "database contract is valid" if ok else "database contract failed",
                                 detail={"path": str(path), **result}))
        except Exception as exc:  # noqa: BLE001
            checks.append(_check(name, "FAIL", "database is missing or unreadable",
                                 detail={"path": str(path), "error": type(exc).__name__}))

    if config.postgres_credential_file.is_file():
        try:
            from mova_fpl.postgres.store import latest_version, status as postgres_status

            pg_status = postgres_status(config)
            applied = [int(item["version"]) for item in pg_status["migrations"]]
            current_schema = bool(applied) and applied[-1] == latest_version()
            pg_ok = pg_status["status"] == "healthy" and current_schema
            checks.append(_check(
                "postgres_shadow", "PASS" if pg_ok else "WARN",
                "PostgreSQL shadow is reachable and current" if pg_ok
                else "PostgreSQL shadow needs attention",
                required=False,
                detail={
                    "server_version": pg_status.get("server_version"),
                    "migrations": applied,
                    "expected_latest": latest_version(),
                    "latest_import_status": (pg_status.get("latest_import") or {}).get("status"),
                    "writer": pg_status.get("writer"),
                    "role": pg_status.get("postgres_role"),
                },
            ))
        except Exception as exc:  # noqa: BLE001
            checks.append(_check(
                "postgres_shadow", "WARN", "PostgreSQL shadow is unavailable",
                required=False,
                detail={"error": type(exc).__name__, "message": str(exc)[:300]},
            ))

        try:
            from mova_fpl.ops.collector.store import CollectorStore

            collector = CollectorStore(config).status()
            sources = {row["source_name"]: row for row in collector["sources"]}
            fpl_ok = (sources.get("fpl_official") or {}).get("health") == "healthy"
            other_bad = [name for name, row in sources.items()
                         if name != "fpl_official" and row.get("health") != "healthy"]
            collector_status = "PASS" if fpl_ok and not other_bad else (
                "WARN" if fpl_ok else "FAIL"
            )
            checks.append(_check(
                "autonomous_data_service", collector_status,
                "all data sources are healthy" if collector_status == "PASS"
                else "one or more data sources need attention",
                required=not fpl_ok,
                detail={"counts": collector["counts"],
                        "sources": [{key: row.get(key) for key in (
                            "source_name", "health", "last_status", "age_seconds",
                            "consecutive_failures"
                        )} for row in collector["sources"]], "non_fpl_issues": other_bad},
            ))
        except Exception as exc:  # noqa: BLE001
            checks.append(_check(
                "autonomous_data_service", "WARN", "data service not initialized",
                required=False, detail={"error": type(exc).__name__,
                                        "message": str(exc)[:300]},
            ))

        try:
            from mova_fpl.ops.analytics_store import AnalyticsStore

            analytics = AnalyticsStore(config).status()
            latest = (analytics.get("latest_scorecards") or [None])[0]
            analytics_status = "WARN" if analytics["status"] == "alert" else "PASS"
            checks.append(_check(
                "model_analytics_service", analytics_status,
                "model analytics is queryable" if analytics_status == "PASS"
                else "latest model scorecard reports drift",
                required=False, detail={"counts": analytics.get("counts"),
                                        "latest_scorecard": latest},
            ))
        except Exception as exc:  # noqa: BLE001
            checks.append(_check(
                "model_analytics_service", "WARN", "analytics service not initialized",
                required=False, detail={"error": type(exc).__name__,
                                        "message": str(exc)[:300]},
            ))

    model_root = config.artifact_root / "models"
    model_files = sorted(model_root.rglob("*.joblib")) if model_root.is_dir() else []
    model_families = {path.parent.name for path in model_files}
    models_ok = {"minutes", "points"} <= model_families
    checks.append(_check("model_artifacts", "PASS" if models_ok else "FAIL",
                         "required model families are present" if models_ok
                         else "required model families are missing",
                         detail={"root": str(model_root), "count": len(model_files),
                                 "families": sorted(model_families),
                                 "required_families": ["minutes", "points"]}))

    resource_path = config.artifact_root if config.artifact_root.exists() else config.artifact_root.parent
    try:
        disk_free = shutil.disk_usage(resource_path).free
        memory_free = _memory_available_bytes()
        resources_ok = disk_free >= config.disk_gate_bytes and memory_free >= config.memory_gate_bytes
        checks.append(_check("resource_gates", "PASS" if resources_ok else "FAIL",
                             "memory and disk gates pass" if resources_ok else "resource gate failed",
                             detail={"memory_available_bytes": memory_free,
                                     "memory_required_bytes": config.memory_gate_bytes,
                                     "disk_free_bytes": disk_free,
                                     "disk_required_bytes": config.disk_gate_bytes}))
    except OSError as exc:
        checks.append(_check("resource_gates", "FAIL", "resources could not be measured",
                             detail={"error": type(exc).__name__}))

    backups = [item for item in config.backup_root.iterdir() if item.is_dir()] \
        if config.backup_root.is_dir() else []
    latest_backup = max(backups, key=lambda item: item.stat().st_mtime) if backups else None
    backup_age = int(current.timestamp() - latest_backup.stat().st_mtime) if latest_backup else None
    backup_ok = backup_age is not None and backup_age <= 36 * 3600
    checks.append(_check("recent_backup", "PASS" if backup_ok else "WARN",
                         "recent local backup is present" if backup_ok else "recent backup not found",
                         required=False, detail={"age_seconds": backup_age}))

    host = _load_host_probe(config.host_probe_path, current)
    if host.get("available"):
        units = host.get("systemd") or {}
        expected_units = (
            "mova-fpl-stack.service", "mova-fpl-tick.timer",
            "mova-fpl-private-state.timer", "mova-fpl-backup.timer",
            "mova-fpl-watchdog.timer",
            "mova-fpl-analytics.timer",
            "mova-fpl-research.timer",
        )
        bad_units = [name for name in expected_units
                     if (units.get(name) or {}).get("active_state") != "active"]
        host_fresh = host.get("age_seconds") is not None and host["age_seconds"] <= 600
        checks.append(_check("host_probe", "PASS" if host_fresh else "WARN",
                             "host probe is fresh" if host_fresh else "host probe is stale",
                             required=False, detail={"age_seconds": host.get("age_seconds")}))
        checks.append(_check("systemd_units", "PASS" if not bad_units else "FAIL",
                             "required units are active" if not bad_units else "required units are inactive",
                             detail={"inactive": bad_units}))
        if "mova-fpl-collector.timer" in units:
            collector_timer_ok = (
                (units.get("mova-fpl-collector.timer") or {}).get("active_state") == "active"
            )
            checks.append(_check(
                "data_collector_timer", "PASS" if collector_timer_ok else "WARN",
                "data collector timer is active" if collector_timer_ok
                else "data collector timer is inactive",
                required=False, detail=units.get("mova-fpl-collector.timer") or {},
            ))
        api = host.get("api") or {}
        checks.append(_check("api_container", "PASS" if api.get("ready") else "FAIL",
                             "API is ready" if api.get("ready") else "API is not ready",
                             detail={"container_state": api.get("container_state")}))
        if "postgres" in host:
            postgres = host.get("postgres") or {}
            postgres_ok = (postgres.get("container_state") == "running"
                           and postgres.get("container_health") == "healthy"
                           and postgres.get("published_ports") is False)
            checks.append(_check(
                "postgres_container", "PASS" if postgres_ok else "WARN",
                "PostgreSQL shadow is healthy and private" if postgres_ok
                else "PostgreSQL shadow container needs attention",
                required=False, detail=postgres,
            ))
        revisions = host.get("revisions") or {}
        checkout_revision = str(revisions.get("checkout") or "")
        image_revision = str(revisions.get("image") or "")
        aligned = bool(
            checkout_revision and image_revision
            and (
                checkout_revision == image_revision
                or (len(checkout_revision) >= 7 and image_revision.startswith(checkout_revision))
                or (len(image_revision) >= 7 and checkout_revision.startswith(image_revision))
            )
        )
        checks.append(_check("deployment_revision", "PASS" if aligned else "WARN",
                             "checkout and image revisions match" if aligned else "checkout/image revision drift",
                             required=False, detail=revisions))
        browser = host.get("browser") or {}
        profile_ok = bool(browser.get("profile_present"))
        checks.append(_check("browser_profile", "PASS" if profile_ok else "WARN",
                             "persistent browser profile is present" if profile_ok else "browser profile is absent",
                             required=False, detail={"profile_present": profile_ok,
                                                     "container_state": browser.get("container_state")}))
        research_host = host.get("research")
        if isinstance(research_host, dict):
            research_ready = bool(
                research_host.get("auth_present") and research_host.get("queue_present")
            )
            checks.append(_check(
                "research_worker", "PASS" if research_ready else "FAIL",
                "isolated Codex research worker is provisioned" if research_ready
                else "Codex auth or research queue is missing",
                detail=research_host,
            ))
    else:
        checks.append(_check("host_probe", "WARN", "host-level checks are not observable",
                             required=False, detail={"reason": host.get("reason")}))

    if network:
        try:
            boot = json.loads(bootstrap_fetcher(timeout=10, retries=1))
            valid = bool(boot.get("events")) and bool(boot.get("elements"))
            checks.append(_check("fpl_public_api", "PASS" if valid else "FAIL",
                                 "official FPL API is reachable" if valid else "unexpected FPL payload",
                                 detail={"events": len(boot.get("events") or ()),
                                         "players": len(boot.get("elements") or ())}))
        except Exception as exc:  # noqa: BLE001
            checks.append(_check("fpl_public_api", "FAIL", "official FPL API is unavailable",
                                 detail={"error": type(exc).__name__, "message": str(exc)[:300]}))
    else:
        checks.append(_check("fpl_public_api", "WARN", "network check was skipped",
                             required=False))

    required_failures = [item for item in checks if item["status"] == "FAIL" and item["required"]]
    warnings = [item for item in checks if item["status"] == "WARN"]
    overall = "failed" if required_failures else "degraded" if warnings else "healthy"
    return {
        "schema": COMMAND_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "command": "doctor",
        "generated_at": _iso(current),
        "overall_status": overall,
        "summary": {
            "pass": sum(item["status"] == "PASS" for item in checks),
            "warn": len(warnings),
            "fail": sum(item["status"] == "FAIL" for item in checks),
            "required_failures": len(required_failures),
        },
        "checks": checks,
    }


def render_status(payload: dict) -> str:
    gw = payload["gameweek"]
    team = payload["data"]["team_state"]
    controls = payload["runtime"]["controls"]
    tick = payload["operations"]["latest_tick"] or {}
    incidents = payload["operations"]["open_incidents"]
    host = payload["host"]
    scorecard = (payload.get("analytics", {}).get("latest_scorecards") or [{}])[0]
    return "\n".join((
        f"MOVA FPL · {payload['overall_status'].upper()} · {payload['generated_at']}",
        f"GW {gw.get('gw') or '—'} · {gw.get('phase') or 'sin ciclo'} · {gw.get('readiness') or 'sin readiness'} · deadline {gw.get('deadline_at') or '—'}",
        f"Equipo: {team.get('squad_size') or 0}/15 · FT {team.get('free_transfers') if team.get('free_transfers') is not None else '—'} · banco £{(team.get('bank_tenths') or 0) / 10:.1f}m · estado {team.get('quality') or 'ausente'}",
        f"Último tick: {tick.get('status') or 'ausente'} · edad {payload['operations'].get('latest_tick_age_seconds')}s",
        f"Controles: {controls['mode']} / {controls['action_level']} · compliance {controls['compliance_gate']} · kill_switch={str(controls['kill_switch']).lower()} · browser_writes={str(controls['browser_writes']).lower()}",
        f"Fuentes {len(payload['data']['sources'])} · modelos {len(payload['models']['artifacts'])} artefactos/{len(payload['models']['registered'])} registrados · research {payload['research']['signals']} · manifiesto {'sí' if payload['strategy']['manifest'] else 'no'} · incidentes {len(incidents)} · outbox {payload['operations']['outbox_pending']}",
        f"Analytics: GW {scorecard.get('gw') or '—'} · {scorecard.get('variant') or 'sin variante'} · drift {scorecard.get('drift_status') or 'sin scorecard'}",
        f"Host: {'observable' if host.get('available') else 'no observable'} · git {payload['runtime']['git_sha']}",
    ))


def render_doctor(payload: dict) -> str:
    lines = [f"MOVA doctor · {payload['overall_status'].upper()} · {payload['generated_at']}"]
    lines.extend(f"[{item['status']}] {item['name']}: {item['summary']}"
                 for item in payload["checks"])
    summary = payload["summary"]
    lines.append(f"Resultado: {summary['pass']} PASS · {summary['warn']} WARN · {summary['fail']} FAIL")
    return "\n".join(lines)
