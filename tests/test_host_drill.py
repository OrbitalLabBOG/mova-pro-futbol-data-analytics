from __future__ import annotations

import json
from pathlib import Path

import pytest

from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB
from mova_fpl.ops.host_drill import import_evidence, validate


def _payload() -> dict:
    return {
        "schema": "mova-host-drill-v1", "scenario": "api_recovery", "status": "pass",
        "started_at": "2026-08-31T01:00:00Z",
        "finished_at": "2026-08-31T01:00:08Z", "downtime_seconds": 8,
        "revision": "abc1234",
        "checks": {
            "ready_before": True, "unavailable_during": True, "ready_after": True,
            "revision_unchanged": True, "sqlite_integrity_after": True,
        },
        "fpl_state_mutated": False,
    }


def _postgres_payload() -> dict:
    fingerprint = "a" * 64
    return {
        "schema": "mova-host-drill-v1", "scenario": "postgres_recovery",
        "status": "pass", "started_at": "2026-08-31T01:00:00Z",
        "finished_at": "2026-08-31T01:00:45Z", "downtime_seconds": 12,
        "revision": "abc1234",
        "checks": {
            "postgres_ready_before": True,
            "postgres_unavailable_during": True,
            "api_ready_during": True,
            "sqlite_integrity_during": True,
            "postgres_ready_after": True,
            "postgres_parity_after": True,
            "revision_unchanged": True,
            "team_state_unchanged": True,
        },
        "team_state_sha256_before": fingerprint,
        "team_state_sha256_after": fingerprint,
        "fpl_state_mutated": False,
    }


def _browser_payload() -> dict:
    fingerprint = "b" * 64
    return {
        "schema": "mova-host-drill-v1", "scenario": "browser_recovery",
        "status": "pass", "started_at": "2026-08-31T02:00:00Z",
        "finished_at": "2026-08-31T02:00:45Z", "downtime_seconds": 14,
        "revision": "abc1234",
        "checks": {
            "browser_ready_before": True,
            "session_authenticated_before": True,
            "browser_unavailable_during": True,
            "browser_ready_after": True,
            "session_authenticated_after": True,
            "revision_unchanged": True,
            "team_state_unchanged": True,
            "controls_fail_closed": True,
            "initial_service_state_restored": True,
        },
        "team_state_sha256_before": fingerprint,
        "team_state_sha256_after": fingerprint,
        "fpl_state_mutated": False,
    }


def _combined_payload() -> dict:
    fingerprint = "d" * 64
    return {
        "schema": "mova-host-drill-v1", "scenario": "combined_recovery",
        "status": "pass", "started_at": "2026-08-31T03:00:00Z",
        "finished_at": "2026-08-31T03:01:00Z", "downtime_seconds": 25,
        "revision": "abc1234",
        "checks": {
            "services_ready_before": True,
            "all_services_unavailable_during": True,
            "sqlite_integrity_during": True,
            "stored_team_state_unchanged_during": True,
            "postgres_ready_after": True,
            "postgres_parity_after": True,
            "api_ready_after": True,
            "browser_ready_after": True,
            "session_authenticated_after": True,
            "revisions_unchanged": True,
            "private_state_unchanged": True,
            "controls_fail_closed": True,
            "initial_browser_state_restored": True,
        },
        "team_state_sha256_before": fingerprint,
        "team_state_sha256_after": fingerprint,
        "fpl_state_mutated": False,
    }


def _reboot_payload() -> dict:
    fingerprint = "f" * 64
    return {
        "schema": "mova-host-drill-v1", "scenario": "reboot_recovery",
        "status": "pass", "started_at": "2026-08-31T04:00:00Z",
        "finished_at": "2026-08-31T04:08:00Z", "downtime_seconds": 480,
        "revision": "abc1234",
        "checks": {
            "boot_id_changed": True, "stack_ready_after": True,
            "timers_active_after": True, "scheduler_resumed": True,
            "sqlite_integrity_after": True, "postgres_parity_after": True,
            "revision_unchanged": True, "controls_fail_closed": True,
            "team_state_unchanged": True, "idempotency_unique": True,
            "backup_prepared": True,
        },
        "team_state_sha256_before": fingerprint,
        "team_state_sha256_after": fingerprint,
        "fpl_state_mutated": False,
    }


def _offsite_restore_payload() -> dict:
    return {
        "schema": "mova-host-drill-v1", "scenario": "offsite_restore",
        "status": "pass", "started_at": "2026-08-31T05:00:00Z",
        "finished_at": "2026-08-31T05:20:00Z", "downtime_seconds": 1200,
        "revision": "abc1234",
        "checks": {
            "encrypted_backup_present": True, "remote_snapshot_downloaded": True,
            "manifest_verified": True, "sqlite_restore_passed": True,
            "postgres_restore_passed": True, "artifacts_hashes_match": True,
            "credentials_not_persisted": True, "runtime_unchanged": True,
        },
        "fpl_state_mutated": False,
    }


def test_host_drill_import_is_allowlisted_atomic_and_consumes_inbox(tmp_path: Path):
    config = RuntimeConfig(artifact_root=tmp_path / "artifacts", git_sha="abc1234")
    source = config.artifact_root / "host-drills" / "inbox" / "api.json"
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps(_payload()), encoding="utf-8")

    result = import_evidence(config, source)

    assert result["status"] == "pass"
    assert result["fpl_state_mutated"] is False
    assert not source.exists()
    imported = Path(result["artifact_path"])
    assert imported.is_file()
    persisted = json.loads(imported.read_text(encoding="utf-8"))
    assert persisted["checks"] == _payload()["checks"]
    assert set(persisted) == {
        "schema", "scenario", "status", "started_at", "finished_at",
        "downtime_seconds", "revision", "checks", "fpl_state_mutated",
        "host_service_restarted",
    }


@pytest.mark.parametrize("mutation", [
    {"revision": "wrong"},
    {"status": "fail"},
    {"fpl_state_mutated": True},
    {"downtime_seconds": 121},
    {"checks": {"ready_before": True}},
])
def test_host_drill_rejects_untrusted_or_failed_evidence(mutation):
    payload = {**_payload(), **mutation}
    with pytest.raises(ValueError):
        validate(payload, expected_revision="abc1234")


def test_host_drill_rejects_files_outside_inbox(tmp_path: Path):
    config = RuntimeConfig(artifact_root=tmp_path / "artifacts", git_sha="abc1234")
    source = tmp_path / "api.json"
    source.write_text(json.dumps(_payload()), encoding="utf-8")
    with pytest.raises(ValueError, match="inbox"):
        import_evidence(config, source)


def test_postgres_host_drill_is_allowlisted_and_binds_state_fingerprint():
    result = validate(
        _postgres_payload(), expected_revision="abc1234",
        expected_scenario="postgres_recovery",
    )
    assert result["scenario"] == "postgres_recovery"
    assert len(result["checks"]) == 8
    assert result["team_state_sha256_before"] == "a" * 64
    assert result["team_state_sha256_after"] == result["team_state_sha256_before"]


@pytest.mark.parametrize("mutation", [
    {"team_state_sha256_after": "b" * 64},
    {"team_state_sha256_before": "not-a-digest"},
    {"downtime_seconds": 181},
    {"checks": {"postgres_ready_before": True}},
])
def test_postgres_host_drill_rejects_drift_or_invalid_contract(mutation):
    payload = {**_postgres_payload(), **mutation}
    with pytest.raises(ValueError):
        validate(
            payload, expected_revision="abc1234",
            expected_scenario="postgres_recovery",
        )


def test_browser_host_drill_is_allowlisted_and_binds_private_state():
    result = validate(
        _browser_payload(), expected_revision="abc1234",
        expected_scenario="browser_recovery",
    )
    assert result["scenario"] == "browser_recovery"
    assert len(result["checks"]) == 9
    assert result["team_state_sha256_before"] == "b" * 64
    assert result["team_state_sha256_after"] == result["team_state_sha256_before"]


@pytest.mark.parametrize("mutation", [
    {"team_state_sha256_after": "c" * 64},
    {"team_state_sha256_before": "not-a-digest"},
    {"downtime_seconds": 181},
    {"checks": {"browser_ready_before": True}},
])
def test_browser_host_drill_rejects_state_drift_or_invalid_contract(mutation):
    payload = {**_browser_payload(), **mutation}
    with pytest.raises(ValueError):
        validate(
            payload, expected_revision="abc1234",
            expected_scenario="browser_recovery",
        )


def test_combined_host_drill_is_allowlisted_and_binds_private_state():
    result = validate(
        _combined_payload(), expected_revision="abc1234",
        expected_scenario="combined_recovery",
    )
    assert result["scenario"] == "combined_recovery"
    assert len(result["checks"]) == 13
    assert result["team_state_sha256_before"] == "d" * 64


@pytest.mark.parametrize("mutation", [
    {"team_state_sha256_after": "e" * 64},
    {"downtime_seconds": 241},
    {"checks": {"services_ready_before": True}},
])
def test_combined_host_drill_rejects_drift_or_invalid_contract(mutation):
    with pytest.raises(ValueError):
        validate(
            {**_combined_payload(), **mutation}, expected_revision="abc1234",
            expected_scenario="combined_recovery",
        )


def test_reboot_host_drill_is_allowlisted_and_binds_boot_recovery_state():
    result = validate(
        _reboot_payload(), expected_revision="abc1234",
        expected_scenario="reboot_recovery",
    )
    assert result["scenario"] == "reboot_recovery"
    assert len(result["checks"]) == 11
    assert result["team_state_sha256_before"] == "f" * 64


@pytest.mark.parametrize("mutation", [
    {"team_state_sha256_after": "0" * 64},
    {"downtime_seconds": 1201},
    {"checks": {"boot_id_changed": True}},
])
def test_reboot_host_drill_rejects_drift_timeout_or_invalid_contract(mutation):
    with pytest.raises(ValueError):
        validate(
            {**_reboot_payload(), **mutation}, expected_revision="abc1234",
            expected_scenario="reboot_recovery",
        )


def test_offsite_restore_drill_is_allowlisted_and_time_bounded():
    result = validate(
        _offsite_restore_payload(), expected_revision="abc1234",
        expected_scenario="offsite_restore",
    )
    assert result["scenario"] == "offsite_restore"
    assert len(result["checks"]) == 8


@pytest.mark.parametrize("mutation", [
    {"downtime_seconds": 1801},
    {"checks": {"encrypted_backup_present": True}},
    {"fpl_state_mutated": True},
])
def test_offsite_restore_drill_rejects_timeout_partial_or_mutating_evidence(mutation):
    with pytest.raises(ValueError):
        validate(
            {**_offsite_restore_payload(), **mutation}, expected_revision="abc1234",
            expected_scenario="offsite_restore",
        )


def test_host_drill_rejects_scenario_substitution():
    with pytest.raises(ValueError, match="scenario mismatch"):
        validate(
            _postgres_payload(), expected_revision="abc1234",
            expected_scenario="api_recovery",
        )


def test_host_script_has_recovery_trap_and_never_mentions_fpl_writes():
    script = Path("deploy/bin/api-recovery-drill.sh").read_text(encoding="utf-8")
    assert "trap recover_api EXIT" in script
    assert "flock -n 9" in script
    assert "drill host-status" in script
    assert "docker compose stop --timeout 10 api" in script
    assert '"$inbox" "$imported"' in script
    assert '[[ -w "$inbox" && -w "$imported" ]]' in script
    assert "fpl_state_mutated" in script
    assert not any(token in script for token in ("my-team", "transfers", "agent-browser"))


def test_postgres_host_script_locks_writers_and_proves_recovery():
    script = Path("deploy/bin/postgres-recovery-drill.sh").read_text(encoding="utf-8")
    assert "trap recover_postgres EXIT" in script
    assert "docker compose stop --timeout 20 postgres" in script
    assert "mova-fpl-worker.lock" in script
    assert "mova-fpl-collector-host.lock" in script
    assert "mova-fpl-private-state.lock" in script
    assert "timeout 20 /usr/local/bin/mova postgres status" in script
    assert script.count("/usr/local/bin/mova postgres verify") == 2
    assert "team_state_hash" in script
    assert "fpl_state_mutated" in script
    assert script.index("drill host-status") < script.index("mova-fpl-worker.lock")
    assert not any(token in script for token in ("my-team", "transfers", "agent-browser"))


def test_browser_host_script_restores_initial_state_and_never_writes_fpl():
    script = Path("deploy/bin/browser-recovery-drill.sh").read_text(encoding="utf-8")
    assert "trap restore_initial_state EXIT HUP INT TERM" in script
    assert "mova-fpl-browser-recovery-drill.lock" in script
    assert "mova-fpl-private-state.lock" in script
    assert '"$browser_session" collect' in script
    assert "browser_unavailable_during" in script
    assert "team_state_unchanged" in script
    assert "controls_fail_closed" in script
    assert "initial_service_state_restored" in script
    assert "fpl_state_mutated" in script
    assert script.index("drill host-status") < script.index("mova-fpl-private-state.lock")
    assert not any(token in script for token in (
        "execute begin", "execute finalize", "probe-transfers", "browser_writes=true",
    ))


def test_combined_host_script_locks_services_recovers_all_and_never_writes_fpl():
    script = Path("deploy/bin/combined-recovery-drill.sh").read_text(encoding="utf-8")
    assert "trap restore_services EXIT HUP INT TERM" in script
    assert "mova-fpl-combined-recovery-drill.lock" in script
    for lock_name in (
        "mova-fpl-worker.lock", "mova-fpl-collector-host.lock",
        "mova-fpl-analytics-host.lock", "mova-fpl-research-host.lock",
        "mova-fpl-private-state.lock",
    ):
        assert lock_name in script
    assert "docker compose stop --timeout 10 api" in script
    assert "docker compose stop --timeout 20 postgres" in script
    assert "all_services_unavailable_during" in script
    assert "sqlite_integrity_during" in script
    assert "private_state_unchanged" in script
    assert "initial_browser_state_restored" in script
    assert "fpl_state_mutated" in script
    assert script.index("drill host-status") < script.index("mova-fpl-worker.lock")
    assert not any(token in script for token in (
        "execute begin", "execute finalize", "probe-transfers", "browser_writes=true",
    ))


def test_reboot_workflow_requires_two_phases_and_never_reboots_or_writes_fpl():
    prepare = Path("deploy/bin/reboot-recovery-prepare.sh").read_text(encoding="utf-8")
    verify = Path("deploy/bin/reboot-recovery-verify.sh").read_text(encoding="utf-8")
    unit = Path("deploy/systemd/mova-fpl-reboot-recovery.service").read_text(
        encoding="utf-8"
    )
    assert "drill host-status --scenario reboot_recovery" in prepare
    assert "reboot_executed\": False" in prepare
    assert "backup --force" in prepare
    assert "postgres-shadow-backup.sh" in prepare
    assert "expires_epoch=$((prepared_epoch + 600))" in prepare
    assert "reboot-recovery.expired" in prepare
    assert "/proc/sys/kernel/random/boot_id" in prepare
    assert "boot_id_after" in verify and '!= "$boot_id_before"' in verify
    assert "boot_started_epoch > expires_epoch" in verify
    assert "scheduler_resumed" in verify
    assert "idempotency_unique" in verify
    assert "drill import-host" in verify and "--scenario reboot_recovery" in verify
    assert "ConditionPathExists=/var/lib/mova-fpl/runtime/reboot-recovery.pending.json" in unit
    assert "After=mova-fpl-stack.service" in unit
    for script in (prepare, verify):
        assert not any(token in script for token in (
            "systemctl reboot", "shutdown -r", "execute begin", "execute finalize",
            "probe-transfers", "browser_writes=true",
        ))


def test_host_cli_binds_scenario_and_identity(tmp_path: Path, monkeypatch, capsys):
    from mova_fpl.ops.cli import main

    config = RuntimeConfig(
        ops_db=tmp_path / "db" / "ops.db",
        artifact_root=tmp_path / "artifacts",
        git_sha="abc1234",
        sqlite_min_version="3.40.0",
    )
    config.ops_db.parent.mkdir(parents=True)
    OpsDB(config.ops_db, minimum_version=config.sqlite_min_version).migrate()
    source = config.artifact_root / "host-drills" / "inbox" / "postgres.json"
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps(_postgres_payload()), encoding="utf-8")
    monkeypatch.setattr(
        RuntimeConfig, "from_env", classmethod(lambda cls: config),
    )
    arguments = [
        "drill", "import-host", "--file", str(source),
        "--scenario", "postgres_recovery", "--actor", "operator",
        "--reason", "database recovery", "--idempotency-key", "pg-drill-1",
    ]

    assert main(arguments) == 0
    imported = json.loads(capsys.readouterr().out)
    assert imported["scenario"] == "postgres_recovery"
    assert imported["status"] == "pass"
    host_summary = OpsDB(
        config.ops_db, minimum_version=config.sqlite_min_version,
    ).host_recovery_drill_status()
    assert host_summary["status"] == "incomplete"
    assert host_summary["completed"] == 1
    assert host_summary["scenarios"]["postgres_recovery"]["checks"] == 8

    status_arguments = [
        "drill", "host-status", "--scenario", "postgres_recovery",
        "--actor", "operator", "--reason", "database recovery",
        "--idempotency-key", "pg-drill-1",
    ]
    assert main(status_arguments) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["status"] == "completed"
    assert status["reused"] is True

    changed_identity = [*status_arguments]
    changed_identity[changed_identity.index("database recovery")] = "different reason"
    assert main(changed_identity) == 2
    conflict = json.loads(capsys.readouterr().out)
    assert conflict == {
        "schema": "mova-host-drill-status-v1",
        "status": "conflict",
        "scenario": "postgres_recovery",
        "error_code": "idempotency_identity_mismatch",
    }


def test_four_legacy_host_scenarios_no_longer_claim_full_reboot_recovery(tmp_path):
    db = OpsDB(tmp_path / "ops.db", enforce_version=False)
    db.migrate()
    for scenario, checks in (
        ("api_recovery", 5), ("postgres_recovery", 8),
        ("browser_recovery", 9), ("combined_recovery", 13),
    ):
        job_id, reused = db.start_job(
            "host_recovery_drill", f"fixture:{scenario}", f"corr_{scenario}"
        )
        assert reused is False
        db.finish_job(job_id, "completed", output_sha256="a" * 64,
                      metrics={"scenario": scenario, "checks": checks,
                               "passed": checks, "downtime_seconds": 1})

    status = db.host_recovery_drill_status()

    assert status["status"] == "incomplete"
    assert status["completed"] == 4
    assert status["required"] == 5
    assert "reboot_recovery" not in status["scenarios"]


def test_offsite_restore_status_is_independent_from_host_recovery_count(tmp_path):
    db = OpsDB(tmp_path / "ops.db", enforce_version=False)
    db.migrate()
    job_id, reused = db.start_job(
        "host_recovery_drill", "fixture:offsite", "corr_offsite"
    )
    assert reused is False
    db.finish_job(job_id, "completed", output_sha256="7" * 64,
                  metrics={"scenario": "offsite_restore", "checks": 8,
                           "passed": 8, "downtime_seconds": 12})

    assert db.offsite_restore_drill_status()["status"] == "completed"
    assert db.offsite_restore_drill_status()["passed"] == 8
    assert db.host_recovery_drill_status()["completed"] == 0
