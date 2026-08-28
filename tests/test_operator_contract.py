"""HV1-01: contrato estable de status/doctor para humanos y agentes."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mova_fpl.ops.cli import parser
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB
from mova_fpl.ops.operator import build_doctor, build_status, render_doctor, render_status


def _config(tmp_path: Path) -> RuntimeConfig:
    return RuntimeConfig(
        ops_db=tmp_path / "db" / "ops.db",
        trace_db=tmp_path / "db" / "trace.db",
        canonical_db=tmp_path / "db" / "canonical.db",
        artifact_root=tmp_path / "artifacts",
        backup_root=tmp_path / "backups",
        host_probe_path=tmp_path / "runtime" / "host-probe.json",
        lock_path=tmp_path / "runtime.lock",
        disk_gate_bytes=1,
        memory_gate_bytes=1,
        git_sha="abc123",
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
    return config, db, now


def _sqlite(path: Path, tables: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as con:
        for table in tables:
            con.execute(f'CREATE TABLE "{table}"(id INTEGER PRIMARY KEY)')


def _host_probe(config: RuntimeConfig, now: datetime) -> None:
    config.host_probe_path.parent.mkdir(parents=True, exist_ok=True)
    units = {
        name: {"active_state": "active", "unit_file_state": "enabled"}
        for name in (
            "mova-fpl-stack.service", "mova-fpl-tick.timer",
            "mova-fpl-private-state.timer", "mova-fpl-backup.timer",
            "mova-fpl-watchdog.timer",
            "mova-fpl-analytics.timer",
            "mova-fpl-research.timer",
        )
    }
    config.host_probe_path.write_text(json.dumps({
        "schema": "mova-host-probe-v1",
        "observed_at": now.isoformat(),
        "systemd": units,
        "api": {"ready": True, "container_state": "running"},
        "browser": {"profile_present": True, "container_state": "stopped"},
        "revisions": {"checkout": "abc123", "image": "abc123"},
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
    assert "squad_json" not in json.dumps(payload)
    assert "MOVA FPL · HEALTHY" in render_status(payload)


def test_status_degrades_when_heartbeat_is_stale(tmp_path):
    config, db, now = _seed(tmp_path)
    payload = build_status(config, db, now=now + timedelta(hours=1))
    assert payload["overall_status"] == "degraded"
    assert "latest_tick_stale" in payload["status_reasons"]


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
    backup = config.backup_root / "latest"
    backup.mkdir(parents=True)
    _host_probe(config, now)

    def bootstrap(**_kwargs):
        return json.dumps({"events": [{"id": 2}], "elements": [{"id": 1}]}).encode()

    payload = build_doctor(config, db, now=now + timedelta(seconds=10),
                           bootstrap_fetcher=bootstrap)
    assert payload["overall_status"] == "healthy"
    assert payload["summary"]["pass"] == len(payload["checks"])
    assert payload["summary"]["warn"] == 0
    assert payload["summary"]["fail"] == 0
    assert payload["summary"]["required_failures"] == 0
    assert "[PASS] systemd_units" in render_doctor(payload)


def test_doctor_fails_closed_without_required_databases_or_models(tmp_path):
    config, db, now = _seed(tmp_path)
    payload = build_doctor(config, db, now=now, network=False)
    failures = {item["name"] for item in payload["checks"] if item["status"] == "FAIL"}
    assert {"canonical_database", "trace_database", "model_artifacts"} <= failures
    assert payload["overall_status"] == "failed"
    assert payload["summary"]["required_failures"] == 3


def test_cli_exposes_human_and_json_operator_modes():
    assert parser().parse_args(["status", "--json"]).as_json is True
    doctor = parser().parse_args(["doctor", "--json", "--no-network"])
    assert doctor.as_json is True
    assert doctor.no_network is True
