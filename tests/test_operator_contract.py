"""HV1-01: contrato estable de status/doctor para humanos y agentes."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mova_fpl.ops.cli import parser
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB
from mova_fpl.ops.operator import (
    build_doctor, build_safety, build_status, render_doctor, render_status,
)
from mova_fpl.postgres.store import publish_status as publish_postgres_status


def _config(tmp_path: Path) -> RuntimeConfig:
    return RuntimeConfig(
        ops_db=tmp_path / "db" / "ops.db",
        trace_db=tmp_path / "db" / "trace.db",
        canonical_db=tmp_path / "db" / "canonical.db",
        artifact_root=tmp_path / "artifacts",
        research_root=tmp_path / "artifacts" / "research",
        backup_root=tmp_path / "backups",
        host_probe_path=tmp_path / "runtime" / "host-probe.json",
        lock_path=tmp_path / "runtime.lock",
        disk_gate_bytes=1,
        memory_gate_bytes=1,
        git_sha="abc1234",
    )


def _seed(tmp_path: Path) -> tuple[RuntimeConfig, OpsDB, datetime]:
    config = _config(tmp_path)
    db = OpsDB(config.ops_db, enforce_version=False)
    db.migrate()
    db.ensure_defaults(mode="shadow", action_level="A0", compliance_gate="pending",
                       browser_writes=False)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    deadline = now + timedelta(days=3)
    cycle = db.upsert_cycle(config.season, 2, deadline.isoformat(), phase="baseline")
    job, _ = db.start_job("tick", "tick:operator-contract", "corr_contract", cycle_id=cycle)
    db.add_snapshot(
        job_id=job, cycle_id=cycle, source_name="fpl_official",
        captured_at=now.isoformat(), artifact_path=str(config.artifact_root / "source"),
        manifest_sha256="a" * 64, payload_sha256="b" * 64, freshness_seconds=0,
        quality_status="valid", quality={"schema": "test", "event_context": {
            "current_gw": 1, "prior_gw": 1, "prior_settled": False,
            "prior_unstarted_fixtures": 1, "preliminary": True,
            "readiness_reasons": ["prior_gameweek_unsettled"],
        }},
    )
    db.add_team_state(
        job_id=job, cycle_id=cycle, observed_at=now.isoformat(),
        source_name="fpl_authenticated_api",
        squad=[{"element": item} for item in range(1, 16)], free_transfers=1,
        bank_tenths=4, chips=[{"name": "wildcard", "status_for_entry": "available"}],
        fingerprint="c" * 64, artifact_path=str(config.artifact_root / "team"),
        manifest_sha256="d" * 64,
    )
    db.finish_job(job, "completed", metrics={"gw": 2})
    _host_probe(config, now, postgres_running=False)
    return config, db, now


def _dr_observation(now):
    from mova_fpl.ops.dr_health import REQUIRED_CHECKS
    return {"generated_at": now.isoformat(), "revision": "abc1234" + "0" * 33,
            "checks": {name: "pass" for name in REQUIRED_CHECKS},
            "local_backup": {"data_age_seconds": 60},
            "remote_backup": {"data_age_seconds": 60}}


def _sqlite(path: Path, tables: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as con:
        for table in tables:
            con.execute(f'CREATE TABLE "{table}"(id INTEGER PRIMARY KEY)')


def _host_probe(config: RuntimeConfig, now: datetime, *, postgres_running=True) -> None:
    config.host_probe_path.parent.mkdir(parents=True, exist_ok=True)
    units = {
        name: {"active_state": "active", "unit_file_state": "enabled"}
        for name in (
            "mova-fpl-stack.service", "mova-fpl-collector.timer",
            "mova-fpl-backup.timer", "mova-fpl-analytics.timer",
        )
    }
    units.update({
        name: {
            "active_state": "inactive", "sub_state": "dead",
            "result": "success", "exec_main_status": 0,
        }
        for name in (
            "mova-fpl-backup.service",
            "mova-fpl-collector.service", "mova-fpl-analytics.service",
            "mova-fpl-research.service",
        )
    })
    config.host_probe_path.write_text(json.dumps({
        "schema": "mova-host-probe-v1",
        "observed_at": now.isoformat(),
        "dr_observation": _dr_observation(now),
        "local_backup": {"sqlite_age_seconds": 3600, "postgres_age_seconds": 3600,
                         "data_age_seconds": 3600},
        "systemd": units,
        "api": {"ready": True, "container_state": "running"},
        "postgres": {
            "container_state": "running" if postgres_running else "stopped", "container_health": "healthy",
            "published_ports": False, "role": "shadow",
        },
        "browser": {"profile_present": True, "container_state": "stopped"},
        "revisions": {
            "checkout": "abc1234",
            "image": "abc1234def567890abc1234def567890abc1234d",
        },
    }), encoding="utf-8")


def test_status_contract_is_versioned_and_sanitized(tmp_path):
    config, db, now = _seed(tmp_path)
    payload = build_status(config, db, now=now + timedelta(seconds=10))

    assert payload["schema"] == "mova-fpl-operator-v1"
    assert payload["schema_version"] == "1.0"
    assert payload["overall_status"] == "healthy"
    assert payload["gameweek"]["gw"] == 2
    assert payload["gameweek"]["readiness"] == "preliminary"
    assert payload["gameweek"]["prior_gameweek_settled"] is False
    assert payload["data"]["team_state"]["squad_size"] == 15
    assert payload["data"]["team_state"]["free_transfers"] == 1
    assert payload["runtime"]["controls"]["browser_writes"] is False
    assert payload["storage"] == {
        "operational_writer": "sqlite",
        "postgres_role": "unavailable",
        "postgres": {"status": "unavailable", "read_parity": {"status": "missing"}},
    }
    assert "squad_json" not in json.dumps(payload)
    assert "MOVA FPL · HEALTHY" in render_status(payload)

    safety = build_safety(config, db, now=now + timedelta(seconds=10))
    assert safety["schema"] == "mova-safety-summary-v1"
    assert safety["verdict"] == "safe_to_wait"
    assert safety["controls"]["kill_switch"] is True
    assert "squad_json" not in json.dumps(safety)


def test_stale_tick_no_longer_degrades_status_or_doctor(tmp_path):
    """ADR-022: el tick no es heartbeat; ni status ni doctor lo exigen."""
    config, db, now = _seed(tmp_path)
    later = now + timedelta(hours=1)
    payload = build_status(config, db, now=later)
    assert "latest_tick_stale" not in payload["status_reasons"]
    assert "latest_tick_not_successful" not in payload["status_reasons"]
    doctor = build_doctor(config, db, now=later, network=False)
    assert all(item["name"] != "scheduler_heartbeat" for item in doctor["checks"])


def test_status_and_doctor_surface_failed_scheduled_service(tmp_path):
    config, db, now = _seed(tmp_path)
    _host_probe(config, now)
    probe = json.loads(config.host_probe_path.read_text(encoding="utf-8"))
    probe["systemd"]["mova-fpl-research.service"].update({
        "active_state": "failed", "sub_state": "failed",
        "result": "failed", "exec_main_status": 1,
    })
    config.host_probe_path.write_text(json.dumps(probe), encoding="utf-8")

    status = build_status(config, db, now=now + timedelta(seconds=10))
    doctor = build_doctor(
        config, db, now=now + timedelta(seconds=10), network=False,
    )
    service_check = next(
        item for item in doctor["checks"]
        if item["name"] == "systemd_service_results"
    )

    assert status["overall_status"] == "degraded"
    assert "failed_systemd_services" in status["status_reasons"]
    assert service_check["status"] == "WARN" and service_check["required"] is False
    assert service_check["detail"]["failed"] == ["mova-fpl-research.service"]


def test_status_keeps_failed_job_auditable_but_clears_recovered_failure(tmp_path):
    config, db, now = _seed(tmp_path)
    failed_id, _ = db.start_job("recoverable_fixture", "fixture:failed", "corr_failed")
    db.finish_job(failed_id, "failed", error_code="FixtureError")

    failed = build_status(config, db, now=now + timedelta(seconds=1))
    assert "failed_jobs_last_24h" in failed["status_reasons"]
    assert any(row["job_id"] == failed_id
               for row in failed["operations"]["failed_jobs_last_24h"])

    recovered_id, _ = db.start_job(
        "recoverable_fixture", "fixture:recovered", "corr_recovered"
    )
    db.finish_job(recovered_id, "completed")
    recovered = build_status(config, db, now=now + timedelta(seconds=2))

    assert "failed_jobs_last_24h" not in recovered["status_reasons"]
    assert all(row["job_id"] != failed_id
               for row in recovered["operations"]["failed_jobs_last_24h"])
    with db.connect(readonly=True) as con:
        assert con.execute(
            "SELECT status FROM job_runs WHERE job_id=?", (failed_id,)
        ).fetchone()[0] == "failed"


def test_status_reads_sanitized_postgres_parity_without_database_secret(tmp_path):
    config, db, now = _seed(tmp_path)
    publish_postgres_status(config, {
        "status": "healthy", "server_version": "17.11",
        "migrations": [{"version": item} for item in range(1, 17)],
        "latest_import": {
            "import_run_id": "pgimport_test", "status": "completed",
            "git_sha": "abc123", "started_at": now.isoformat(),
            "finished_at": now.isoformat(),
        },
        "read_parity": {
            "status": "pass", "checked_tables": 49,
            "exact_tables": 48, "aggregate_tables": 1, "failed_tables": 0,
        },
        "role_separation": {"status": "pass"},
        "writer": "sqlite", "postgres_role": "shadow",
    })

    payload = build_status(config, db, now=now + timedelta(seconds=10))

    assert payload["overall_status"] == "healthy"
    assert payload["storage"]["operational_writer"] == "sqlite"
    assert payload["storage"]["postgres_role"] == "shadow"
    assert payload["storage"]["postgres"]["migration_count"] == 16
    assert payload["storage"]["postgres"]["import_fresh"] is True
    assert payload["storage"]["postgres"]["read_parity"]["status"] == "pass"
    assert payload["storage"]["postgres"]["role_separation"]["status"] == "pass"


def test_status_surfaces_missing_parity_artifact_when_postgres_is_running(tmp_path):
    config, db, now = _seed(tmp_path)
    _host_probe(config, now)

    payload = build_status(config, db, now=now + timedelta(seconds=10))

    assert payload["overall_status"] == "degraded"
    assert "postgres_shadow_status_unavailable" in payload["status_reasons"]


def test_doctor_passes_complete_runtime_contract(tmp_path):
    config, db, now = _seed(tmp_path)
    _sqlite(config.canonical_db, ("player_gameweek",))
    with sqlite3.connect(config.canonical_db) as con:
        con.execute("INSERT INTO player_gameweek DEFAULT VALUES")
    _sqlite(config.trace_db,
            ("agent_runs", "gw_decisions", "model_versions", "interventions"))
    for family in ("minutes", "points"):
        model = config.artifact_root / "models" / family / f"{family}.joblib"
        model.parent.mkdir(parents=True, exist_ok=True)
        model.write_bytes(b"model")
    _host_probe(config, now)

    def bootstrap(**_kwargs):
        return json.dumps({"events": [{"id": 2}], "elements": [{"id": 1}]}).encode()

    payload = build_doctor(config, db, now=now + timedelta(seconds=10),
                           bootstrap_fetcher=bootstrap)
    assert payload["overall_status"] == "healthy"
    assert payload["summary"]["warn"] == 0
    assert payload["summary"]["fail"] == 0
    assert payload["summary"]["required_failures"] == 0
    assert "[PASS] systemd_units" in render_doctor(payload)


def test_doctor_fails_closed_without_required_databases_or_models(tmp_path):
    config, db, now = _seed(tmp_path)
    payload = build_doctor(config, db, now=now, network=False)
    failures = {item["name"] for item in payload["checks"] if item["status"] == "FAIL"}
    assert {"canonical_database", "trace_database", "model_artifacts",
            "postgres_container"} <= failures
    assert payload["overall_status"] == "failed"
    assert payload["summary"]["required_failures"] == 4
    assert "scheduler_heartbeat" not in {item["name"] for item in payload["checks"]}


def test_doctor_no_longer_inspects_agent_queue(tmp_path):
    config, db, now = _seed(tmp_path)
    payload = build_doctor(config, db, now=now, network=False)
    assert all(item["name"] != "agent_queue_integrity" for item in payload["checks"])


def test_cli_exposes_human_and_json_operator_modes():
    assert parser().parse_args(["status", "--json"]).as_json is True
    doctor = parser().parse_args(["doctor", "--json", "--no-network"])
    assert doctor.as_json is True
    assert doctor.no_network is True
    assert parser().parse_args(["safety"]).command == "safety"
    assert parser().parse_args(["alerts", "dispatch"]).limit == 20
    assert parser().parse_args(["alerts", "channel"]).alerts_command == "channel"
    parsed_alert_test = parser().parse_args([
        "alerts", "test", "--actor", "codex", "--reason", "prove",
        "--idempotency-key", "ping-v1",
    ])
    assert parsed_alert_test.alerts_command == "test"
    retry = parser().parse_args([
        "alerts", "retry", "--outbox-id", "outbox_test",
        "--actor", "operator", "--reason", "sink restored",
    ])
    assert retry.outbox_id == "outbox_test"
    drill = parser().parse_args([
        "drill", "resilience", "--actor", "operator", "--reason", "rehearsal",
        "--idempotency-key", "drill-1",
    ])
    assert drill.drill_command == "resilience"
    host_drill = parser().parse_args([
        "drill", "import-host", "--file", "/tmp/evidence.json",
        "--actor", "operator", "--reason", "api recovery",
        "--idempotency-key", "host-drill-1",
    ])
    assert host_drill.drill_command == "import-host"
    host_status = parser().parse_args([
        "drill", "host-status", "--scenario", "postgres_recovery",
        "--actor", "operator", "--reason", "database recovery",
        "--idempotency-key", "host-drill-1",
    ])
    assert host_status.drill_command == "host-status"
    assert host_status.scenario == "postgres_recovery"


def test_copilot_lineup_scope_does_not_require_delivery_or_research_timers(tmp_path):
    """ADR-021: an armed legacy scope never makes retired timers mandatory."""
    from dataclasses import replace
    from mova_fpl.ops.operator import build_safety
    config, db, now = _seed(tmp_path)
    db.set_control("delivery_scope", "lineup-v1", actor="test", reason="legacy scope left armed")
    _host_probe(config, now)
    payload = build_doctor(config, db, now=now + timedelta(seconds=10), network=False)
    units = next(item for item in payload["checks"] if item["name"] == "systemd_units")
    assert units["status"] == "PASS", units
    status = build_status(config, db, now=now + timedelta(seconds=10))
    assert status["operating_model"] == "copilot"
    assert status["runtime"]["operating_model"] == "copilot"
    assert build_safety(config, db, now=now + timedelta(seconds=10))["operating_model"] == "copilot"

    opted = replace(config, enable_scheduled_delivery=True)
    payload = build_doctor(opted, db, now=now + timedelta(seconds=10), network=False)
    units = next(item for item in payload["checks"] if item["name"] == "systemd_units")
    assert units["status"] == "PASS", units  # ADR-022: delivery nunca se exige
    assert build_status(opted, db, now=now)["operating_model"] == "scheduled_delivery"


REQUIRED_DOCTOR_CHECKS = {
    "ops_database", "ops_schema", "model_artifacts", "resource_gates", "recent_backup",
    "systemd_units", "api_container", "postgres_container",
}


def _healthy_runtime(tmp_path):
    config, db, now = _seed(tmp_path)
    _sqlite(config.canonical_db, ("player_gameweek",))
    with sqlite3.connect(config.canonical_db) as con:
        con.execute("INSERT INTO player_gameweek DEFAULT VALUES")
    _sqlite(config.trace_db,
            ("agent_runs", "gw_decisions", "model_versions", "interventions"))
    for family in ("minutes", "points"):
        model = config.artifact_root / "models" / family / f"{family}.joblib"
        model.parent.mkdir(parents=True, exist_ok=True)
        model.write_bytes(b"model")
    _host_probe(config, now)
    return config, db, now


def test_slim_doctor_required_set_and_expected_units(tmp_path):
    config, db, now = _healthy_runtime(tmp_path)
    probe = json.loads(config.host_probe_path.read_text())
    # Unidades retiradas apagadas/ausentes no deben afectar al doctor.
    for retired in ("tick", "private-state", "watchdog", "postgres-sync",
                    "backup-retention", "delivery", "dr-status"):
        probe["systemd"].pop(f"mova-fpl-{retired}.timer", None)
    probe["dr_observation"] = {}
    config.host_probe_path.write_text(json.dumps(probe))
    payload = build_doctor(config, db, now=now + timedelta(seconds=10), network=False)
    required = {item["name"] for item in payload["checks"] if item["required"]}
    assert REQUIRED_DOCTOR_CHECKS <= required
    assert not {"scheduler_heartbeat", "agent_queue_integrity", "private_team_state",
                "disaster_recovery_observation"} & required
    assert payload["summary"]["required_failures"] == 0, payload["summary"]
    units = next(item for item in payload["checks"] if item["name"] == "systemd_units")
    assert units["status"] == "PASS"
    # Colector parado sí es obligatorio.
    del probe["systemd"]["mova-fpl-collector.timer"]
    config.host_probe_path.write_text(json.dumps(probe))
    payload = build_doctor(config, db, now=now + timedelta(seconds=10), network=False)
    units = next(item for item in payload["checks"] if item["name"] == "systemd_units")
    assert units["detail"]["inactive"] == ["mova-fpl-collector.timer"]


def test_doctor_backup_age_uses_36h_rpo(tmp_path):
    config, db, now = _healthy_runtime(tmp_path)
    probe = json.loads(config.host_probe_path.read_text())
    probe["local_backup"]["data_age_seconds"] = 30 * 3600
    config.host_probe_path.write_text(json.dumps(probe))
    check = next(i for i in build_doctor(config, db, now=now + timedelta(seconds=10),
                                         network=False)["checks"] if i["name"] == "recent_backup")
    assert check["status"] == "PASS"
    probe["local_backup"]["data_age_seconds"] = 37 * 3600
    config.host_probe_path.write_text(json.dumps(probe))
    check = next(i for i in build_doctor(config, db, now=now + timedelta(seconds=10),
                                         network=False)["checks"] if i["name"] == "recent_backup")
    assert check["status"] == "FAIL" and check["required"] is True


def test_harness_incidents_do_not_make_safety_unsafe(tmp_path):
    config, db, now = _seed(tmp_path)
    for severity, title in (
        ("P0", "Scheduler heartbeat unhealthy"), ("P1", "Agent queue integrity unhealthy"),
        ("P0", "Autonomous cycle deadline risk"),
        ("P1", "Backup recovery observation unhealthy"),
        ("P0", "Ejecución FPL ambigua"), ("P1", "Local storage headroom low"),
        ("P2", "Shadow decision falló"),
    ):
        db.open_incident_once(severity, title)
    safety = build_safety(config, db, now=now + timedelta(seconds=10))
    assert safety["verdict"] == "safe_to_wait"
    assert safety["alerts"]["critical_open"] == 0
    assert safety["alerts"]["total_open"] == 7
    db.open_incident_once("P1", "Servicio de datos MOVA falló")
    assert build_safety(config, db, now=now + timedelta(seconds=10))["verdict"] == "unsafe"
