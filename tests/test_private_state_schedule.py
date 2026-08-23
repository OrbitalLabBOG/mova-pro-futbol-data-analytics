from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB
from mova_fpl.ops.private_schedule import assess
from mova_fpl.ops.schedule import private_state_cadence_seconds


UTC = timezone.utc
DEADLINE = "2026-08-28T17:30:00Z"


def test_cadencia_privada_se_adapta_al_deadline():
    deadline = datetime.fromisoformat(DEADLINE.replace("Z", "+00:00"))
    assert private_state_cadence_seconds(DEADLINE, deadline - timedelta(days=2)) == 21600
    assert private_state_cadence_seconds(DEADLINE, deadline - timedelta(hours=24)) == 3600
    assert private_state_cadence_seconds(DEADLINE, deadline - timedelta(hours=3)) == 900
    assert private_state_cadence_seconds(DEADLINE, deadline - timedelta(minutes=30)) == 300
    assert private_state_cadence_seconds(DEADLINE, deadline + timedelta(minutes=1)) == 21600


def test_gate_captura_si_falta_y_omite_si_esta_fresco(tmp_path):
    config = RuntimeConfig(
        ops_db=tmp_path / "ops.db", artifact_root=tmp_path / "artifacts",
        disk_gate_bytes=1, memory_gate_bytes=1,
    )
    db = OpsDB(config.ops_db, enforce_version=False)
    db.migrate()
    now = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    bootstrap = json.dumps({
        "events": [{"id": 2, "deadline_time": DEADLINE, "is_next": True}],
    }).encode()

    missing = assess(config, db, now=now, bootstrap=bootstrap)
    assert missing["due"] is True
    assert missing["reason"] == "no_current_event_snapshot"
    assert missing["cadence_seconds"] == 3600

    cycle = db.upsert_cycle(config.season, 2, DEADLINE, phase="preflight")
    job, _ = db.start_job("private_team_state", "private:test", "corr_test", cycle_id=cycle)
    observed = (now - timedelta(minutes=10)).isoformat(timespec="milliseconds")
    db.add_team_state(
        job_id=job, cycle_id=cycle, observed_at=observed,
        source_name="fpl_authenticated_api", squad=[{"element": i} for i in range(1, 16)],
        free_transfers=1, bank_tenths=0, chips=[], fingerprint="f" * 64,
        artifact_path=str(tmp_path / "team-state"), manifest_sha256="a" * 64,
    )
    fresh = assess(config, db, now=now, bootstrap=bootstrap)
    assert fresh["due"] is False
    assert fresh["reason"] == "snapshot_fresh"
    assert fresh["age_seconds"] == 600


def test_gate_exige_captura_al_vencer_cadencia(tmp_path):
    config = RuntimeConfig(
        ops_db=tmp_path / "ops.db", artifact_root=tmp_path / "artifacts",
        disk_gate_bytes=1, memory_gate_bytes=1,
    )
    db = OpsDB(config.ops_db, enforce_version=False)
    db.migrate()
    deadline = datetime.fromisoformat(DEADLINE.replace("Z", "+00:00"))
    now = deadline - timedelta(minutes=20)
    bootstrap = json.dumps({
        "events": [{"id": 2, "deadline_time": DEADLINE, "is_next": True}],
    }).encode()
    cycle = db.upsert_cycle(config.season, 2, DEADLINE, phase="hard_stop")
    job, _ = db.start_job("private_team_state", "private:stale", "corr_test", cycle_id=cycle)
    db.add_team_state(
        job_id=job, cycle_id=cycle,
        observed_at=(now - timedelta(minutes=6)).isoformat(timespec="milliseconds"),
        source_name="fpl_authenticated_api", squad=[{"element": i} for i in range(1, 16)],
        free_transfers=1, bank_tenths=0, chips=[], fingerprint="f" * 64,
        artifact_path=str(tmp_path / "team-state"), manifest_sha256="a" * 64,
    )
    result = assess(config, db, now=now, bootstrap=bootstrap)
    assert result["due"] is True
    assert result["cadence_seconds"] == 300
    assert result["age_seconds"] == 360
