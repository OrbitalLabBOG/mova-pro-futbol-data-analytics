from datetime import datetime, timedelta, timezone
import json

import pytest

from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB
from mova_fpl.ops.dr_health import REQUIRED_CHECKS, assess_backup_freshness
from mova_fpl.ops.watchdog import DR_INCIDENT_TITLE, run

NOW = datetime(2026, 10, 4, 22, tzinfo=timezone.utc)
SHA = "a" * 40


def observation():
    return {"generated_at": NOW.isoformat(), "revision": SHA,
            "checks": {name: "pass" for name in REQUIRED_CHECKS},
            "local_backup": {"data_age_seconds": 24000},
            "remote_backup": {"data_age_seconds": 24000}}


def assess(report, now=NOW):
    return assess_backup_freshness({"dr_observation": report}, revision=SHA[:7], now=now)


def test_backup_age_advances_between_hourly_reports():
    assert assess(observation())["healthy"] is True
    after = assess(observation(), NOW + timedelta(minutes=21))
    assert after["report_age_seconds"] == 1260
    assert after["data_age_seconds"]["remote_backup"] == 25260
    assert after["healthy"] is False
    assert "remote_backup_outside_rpo" in after["reasons"]
    assert after["host_reconstruction_proven"] is False


@pytest.mark.parametrize("change", [
    {}, {"generated_at": None}, {"generated_at": "2026-10-04T22:00:00"},
    {"generated_at": (NOW + timedelta(minutes=1)).isoformat()},
    {"generated_at": (NOW + timedelta(microseconds=1)).isoformat()},
    {"generated_at": (NOW - timedelta(minutes=91)).isoformat()},
    {"checks": {}}, {"revision": "b" * 40},
    {"local_backup": {"data_age_seconds": True}},
    {"remote_backup": {"data_age_seconds": -1}}, {"remote_backup": []},
])
def test_missing_invalid_stale_future_or_wrong_release_never_pass(change):
    report = {**observation(), **change} if change else {}
    assert assess(report)["healthy"] is False


def test_blocked_check_never_passes_with_fresh_timestamps():
    report = observation()
    report["checks"]["external_snapshot_within_rpo"] = "blocked"
    assert "dr_preflight_blocked" in assess(report)["reasons"]


def test_watchdog_dr_failure_is_deduplicated_then_resolved_only_by_fresh_report(tmp_path):
    config = RuntimeConfig(host_probe_path=tmp_path / "host.json", git_sha=SHA,
                           research_root=tmp_path / "research")
    db = OpsDB(tmp_path / "ops.db", enforce_version=False)
    db.migrate()
    job, _ = db.start_job("tick", "tick:dr-fixture", "corr-dr")
    db.finish_job(job, "completed")
    current = datetime.now(timezone.utc)
    sent = []
    def check():
        return run(db, config=config, now=current, sink=lambda event: sent.append(event["event_key"]))
    first = check()
    duplicate = check()
    assert first["reason"] == "backup_recovery_observation_unhealthy"
    assert first["alerts"]["delivered"] == 1
    assert duplicate["alerts"]["claimed"] == 0
    stale = {**observation(), "generated_at": (current - timedelta(hours=2)).isoformat()}
    def publish(report):
        config.host_probe_path.write_text(json.dumps({"schema": "mova-host-probe-v1",
            "observed_at": current.isoformat(), "dr_observation": report}))
    publish(stale)
    assert check()["disaster_recovery"]["healthy"] is False
    fresh = {**observation(), "generated_at": current.isoformat()}
    publish(fresh)
    recovered = check()
    assert recovered["status"] == "ok"
    assert recovered["resolved_by_domain"]["disaster_recovery"] == 1
    with db.connect(readonly=True) as con:
        rows = con.execute("SELECT severity,status FROM incidents WHERE title=?", (DR_INCIDENT_TITLE,)).fetchall()
    assert [(r["severity"], r["status"]) for r in rows] == [("P1", "resolved")]
    assert len(sent) == 1
