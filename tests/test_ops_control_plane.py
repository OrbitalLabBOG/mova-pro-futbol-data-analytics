"""Control plane local: esquema, auditoría, backup e idempotencia."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mova_fpl.ops.backup import create_backup
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB
from mova_fpl.ops.harness import Harness
from mova_fpl.ops.tick import TickRunner


def _config(tmp_path: Path, *, shadow: bool = False) -> RuntimeConfig:
    return RuntimeConfig(
        ops_db=tmp_path / "db" / "ops.db",
        trace_db=tmp_path / "db" / "trace.db",
        canonical_db=tmp_path / "db" / "canonical.db",
        artifact_root=tmp_path / "artifacts",
        backup_root=tmp_path / "backups",
        lock_path=tmp_path / "runtime.lock",
        disk_gate_bytes=1,
        memory_gate_bytes=1,
        enable_shadow_decision=shadow,
        tick_bucket_seconds=300,
    )


def _db(config: RuntimeConfig) -> OpsDB:
    return OpsDB(config.ops_db, enforce_version=False)


def _official_sources() -> tuple[bytes, bytes]:
    teams = [{"id": i, "name": f"T{i}"} for i in range(1, 21)]
    elements = [
        {"id": i, "element_type": 3, "team": i, "first_name": "Player",
         "second_name": str(i), "web_name": str(i), "now_cost": 50,
         "status": "a", "news": "", "selected_by_percent": "0"}
        for i in range(1, 21)
    ]
    boot = {"events": [{"id": 1, "deadline_time": "2026-08-21T17:30:00Z",
                         "is_next": True}], "teams": teams, "elements": elements}
    fixtures = [
        {"id": i, "event": 1, "team_h": i, "team_a": i + 10,
         "kickoff_time": "2026-08-22T14:00:00Z"}
        for i in range(1, 11)
    ]
    return json.dumps(boot).encode(), json.dumps(fixtures).encode()


def test_schema_controls_jobs_y_auditoria(tmp_path):
    config = _config(tmp_path)
    db = _db(config)
    assert db.migrate() == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]
    assert db.migrate() == []
    db.ensure_defaults(mode="shadow", action_level="A0", compliance_gate="pending",
                       browser_writes=False)
    controls = db.controls()
    assert controls["kill_switch"]["value"] is True
    assert controls["browser_writes"]["value"] is False

    cycle = db.upsert_cycle("2026-27", 1, "2026-08-21T17:30:00Z", phase="settlement")
    job, reused = db.start_job("tick", "tick:1", "corr_test")
    assert not reused
    db.bind_job_cycle(job, cycle)
    harness = Harness(db, job, correlation_id="corr_test", cycle_id=cycle)
    assert harness.call("bytes_are_summarized", lambda: {"payload": b"private bytes"})
    db.add_team_state(
        job_id=job, cycle_id=cycle, observed_at="2026-08-21T12:00:00Z",
        source_name="fpl_authenticated_api", squad=[{"element": i} for i in range(1, 16)],
        free_transfers=1, bank_tenths=0, chips=[], fingerprint="f" * 64,
        artifact_path=str(tmp_path / "team-state"), manifest_sha256="a" * 64,
    )
    db.add_team_state(
        job_id=job, cycle_id=cycle, observed_at="2026-08-21T12:10:00Z",
        source_name="fpl_authenticated_api", squad=[{"element": i} for i in range(1, 16)],
        free_transfers=1, bank_tenths=0, chips=[], fingerprint="f" * 64,
        artifact_path=str(tmp_path / "team-state-2"), manifest_sha256="b" * 64,
    )
    db.finish_job(job, "completed", metrics={"gw": 1})
    assert db.start_job("tick", "tick:1", "other") == (job, True)
    assert db.quick_check() == "ok"

    with db.connect(readonly=True) as con:
        detail = json.loads(con.execute(
            "SELECT detail_json FROM job_steps WHERE step_name='bytes_are_summarized'"
        ).fetchone()[0])
        audits = [row[0] for row in con.execute(
            "SELECT event_type FROM audit_events ORDER BY occurred_at"
        )]
    assert detail["payload"]["size"] == len(b"private bytes")
    assert "private bytes" not in json.dumps(detail)
    assert "job_started" in audits and "job_completed" in audits
    assert db.status()["latest_team_state"]["free_transfers"] == 1
    assert len(db.recent("team_state_snapshots")) == 2
    with db.connect(readonly=True) as con:
        tables = {row[0] for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    assert {"gameweek_settlements", "gameweek_reviews", "review_player_outcomes",
            "change_proposals", "season_plans", "cycle_manifests",
            "research_runs", "research_documents", "research_conflicts",
            "cost_ledger", "agent_budget_reservations",
            "change_proposal_evaluations", "lessons",
            "model_bundle_releases", "model_bundle_release_events"} <= tables
    assert {"decision_envelopes", "decision_candidates",
            "decision_validation_checks"} <= tables
    assert {"execution_plans", "execution_preflight_checks"} <= tables


def test_harness_summarizes_nested_payloads_and_redacts_sensitive_keys(tmp_path):
    db = _db(_config(tmp_path))
    db.migrate()
    job, _ = db.start_job("test", "test:safe-detail", "corr_safe")
    harness = Harness(db, job, correlation_id="corr_safe")
    payload = {
        "entry": {
            "entry_id": 3609854,
            "entry_payload": {
                "player_first_name": "private-first",
                "player_last_name": "private-last",
            },
        },
        "players": [{"element": value, "web_name": f"P{value}"} for value in range(50)],
        "authorization": "private-bearer",
    }
    assert harness.call("safe_nested_payload", lambda: payload) == payload
    with db.connect(readonly=True) as con:
        detail = json.loads(con.execute(
            "SELECT detail_json FROM job_steps WHERE step_name='safe_nested_payload'"
        ).fetchone()[0])
    serialized = json.dumps(detail)
    assert "private-first" not in serialized
    assert "private-last" not in serialized
    assert "private-bearer" not in serialized
    assert detail["entry"]["entry_payload"] == {"type": "dict", "items": 2}
    assert detail["players"] == {"type": "list", "items": 50}
    assert detail["authorization"] == {"type": "redacted"}


def test_browser_write_gate_fails_closed(tmp_path):
    config = replace(_config(tmp_path), enable_browser_writes=True)
    try:
        config.validate()
    except ValueError as exc:
        assert "browser writes" in str(exc)
    else:
        raise AssertionError("una configuración A0 no puede habilitar browser writes")


def test_verified_execution_sella_propuestas_shadow_tardias(tmp_path):
    config = _config(tmp_path)
    db = _db(config)
    db.migrate()
    cycle = db.upsert_cycle("2026-27", 2, "2026-08-28T17:30:00Z", phase="preflight")
    job, _ = db.start_job("test", "test:verified-cycle", "corr_verified", cycle_id=cycle)
    shadow = db.record_decision(
        job_id=job, cycle_id=cycle, mode="shadow", status="staged",
        policy_version="test", expected_points=50.0, chip="wildcard",
        fingerprint="shadow", manifest_sha256="a" * 64, artifact_path="shadow.md",
    )
    verified = db.record_decision(
        job_id=job, cycle_id=cycle, mode="guarded_human_reviewed",
        status="executed_verified", policy_version="test", expected_points=None,
        chip=None, fingerprint="verified", manifest_sha256="b" * 64,
        artifact_path="verified.json",
    )
    with db.transaction() as con:
        con.execute(
            """INSERT INTO web_executions(
            execution_id,decision_id,action_level,envelope_sha256,status,finished_at)
            VALUES(?,?,?,?,?,?)""",
            ("execution_verified", verified, "A1", "c" * 64, "verified",
             "2026-08-28T16:00:00Z"),
        )

    sealed = db.seal_verified_decision_cycle(
        cycle, correlation_id="corr_verified", job_id=job,
    )
    assert sealed and sealed["superseded_shadow_decisions"] == 1
    assert sealed["decision_id"] == verified
    assert db.seal_verified_decision_cycle(
        cycle, correlation_id="corr_verified", job_id=job,
    )["superseded_shadow_decisions"] == 0
    with db.connect(readonly=True) as con:
        assert con.execute(
            "SELECT status FROM decision_runs WHERE decision_id=?", (shadow,)
        ).fetchone()[0] == "superseded"


def test_tick_sella_fuentes_y_es_idempotente(tmp_path, monkeypatch):
    boot_raw, fixtures_raw = _official_sources()
    monkeypatch.setattr("mova_fpl.ops.tick.fetch_bootstrap", lambda: boot_raw)
    monkeypatch.setattr("mova_fpl.ops.tick.fetch_fixtures", lambda: fixtures_raw)

    config = _config(tmp_path)
    db = _db(config)
    db.migrate()
    incident_id = db.open_incident(
        "P1", "Tick MOVA falló", detail={"error_code": "FixtureFailure"}
    )
    runner = TickRunner(config, db)
    now = datetime(2026, 8, 20, 21, 30, tzinfo=timezone.utc)
    first = runner.run(now=now)
    second = runner.run(now=now)
    third = runner.run(now=now + timedelta(minutes=5))

    assert first["status"] == "completed"
    assert first["gw"] == 1
    assert Path(first["snapshot"], "manifest.json").is_file()
    assert second["status"] == "reused"
    assert third["work"] == "skipped_cadence"
    assert db.status()["latest_tick"]["status"] == "completed"
    assert len(db.recent("source_snapshots")) == 1
    step_names = {row["step_name"] for row in db.recent("job_steps", 20)}
    assert "fetch_fpl_bootstrap_events" in step_names
    assert "fetch_fpl_fixtures" in step_names
    metrics = db.prometheus()
    assert "mova_tick_last_duration_seconds" in metrics
    assert 'mova_collector_step_duration_ms{step="fetch_fpl_bootstrap_events"' in metrics
    with db.connect(readonly=True) as con:
        incident = con.execute(
            "SELECT status,resolution FROM incidents WHERE incident_id=?", (incident_id,)
        ).fetchone()
        resolution_audit = con.execute(
            "SELECT actor FROM audit_events WHERE event_type='incident_resolved' "
            "AND subject_id=?", (incident_id,),
        ).fetchone()
    assert incident["status"] == "resolved"
    assert first["job_id"] in incident["resolution"]
    assert resolution_audit["actor"] == "mova-ops"


def test_tick_forzado_omite_cadencia_y_deja_auditoria(tmp_path, monkeypatch):
    boot_raw, fixtures_raw = _official_sources()
    monkeypatch.setattr("mova_fpl.ops.tick.fetch_bootstrap", lambda: boot_raw)
    monkeypatch.setattr("mova_fpl.ops.tick.fetch_fixtures", lambda: fixtures_raw)

    config = _config(tmp_path)
    db = _db(config)
    runner = TickRunner(config, db)
    now = datetime(2026, 8, 20, 21, 30, tzinfo=timezone.utc)
    runner.run(now=now)
    forced = runner.run(
        now=now + timedelta(minutes=1), force=True, actor="test-operator",
        reason="validar fuentes antes de GW", idempotency_key="force:test-gw1",
    )
    reused = runner.run(
        now=now + timedelta(minutes=2), force=True, actor="test-operator",
        reason="validar fuentes antes de GW", idempotency_key="force:test-gw1",
    )

    assert forced["status"] == "completed"
    assert "work" not in forced
    assert reused["status"] == "reused"
    # Los bytes idénticos conservan una sola fuente sellada; el job y la
    # auditoría sí prueban que el refresco excepcional se ejecutó.
    assert len(db.recent("source_snapshots")) == 1
    with db.connect(readonly=True) as con:
        audit = con.execute(
            "SELECT actor,payload_json FROM audit_events "
            "WHERE event_type='forced_tick_requested'"
        ).fetchone()
    assert audit["actor"] == "test-operator"
    assert json.loads(audit["payload_json"])["reason"] == "validar fuentes antes de GW"


def test_backup_online_es_restaurable(tmp_path):
    config = _config(tmp_path)
    db = _db(config)
    db.migrate()
    result = create_backup(config, db, retention_days=35)
    manifest = json.loads((Path(result["path"]) / "manifest.json").read_text())
    assert manifest["schema"] == "mova-fpl-backup-v1"
    assert [item["name"] for item in manifest["files"]] == ["ops.db"]
    restored = OpsDB(Path(result["path"]) / "ops.db", enforce_version=False)
    assert restored.quick_check() == "ok"


def test_backup_forzado_es_auditado_e_idempotente(tmp_path, monkeypatch, capsys):
    from mova_fpl.ops.cli import main

    config = replace(_config(tmp_path), sqlite_min_version="3.0.0")
    db = OpsDB(config.ops_db, enforce_version=False)
    db.migrate()
    monkeypatch.setattr(
        RuntimeConfig, "from_env", classmethod(lambda _cls: config)
    )
    argv = [
        "backup", "--force", "--actor", "codex", "--reason", "post migration",
        "--idempotency-key", "backup:test:v1",
    ]
    assert main(argv) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["status"] == "completed"
    assert main(argv) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "reused"
    with db.connect(readonly=True) as con:
        audit = con.execute(
            "SELECT actor,payload_json FROM audit_events "
            "WHERE event_type='forced_backup_requested'"
        ).fetchone()
    assert audit["actor"] == "codex"
    assert json.loads(audit["payload_json"])["reason"] == "post migration"
