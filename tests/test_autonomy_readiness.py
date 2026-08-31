from __future__ import annotations

from copy import deepcopy

from mova_fpl.ops.cli import parser
from mova_fpl.ops.readiness import evaluate_readiness, prometheus


def _operator() -> dict:
    return {
        "overall_status": "healthy",
        "runtime": {"season": "2026-27", "controls": {
            "action_level": "A0", "browser_writes": False,
            "kill_switch": True, "compliance_gate": "pending", "mode": "shadow",
        }},
        "gameweek": {"cycle_id": "2026-27-gw03", "gw": 3, "readiness": "ready"},
        "data": {
            "team_state": {"quality": "valid", "squad_size": 15,
                           "age_seconds": 10, "max_age_seconds": 300},
            "service": {"status": "healthy"},
        },
        "analytics": {
            "status": "healthy",
            "latest_projection_batches": [
                {"batch_id": "projection_test", "target_gw": 3, "status": "approved"}
            ],
        },
        "strategy": {"manifest": {"manifest_id": "manifest_test",
                                    "content_sha256": "a" * 64}},
        "operations": {"open_incidents": []},
        "storage": {"postgres": {
            "status": "healthy", "import_fresh": True,
            "read_parity": {"status": "pass"},
            "role_separation": {"status": "pass"},
            "import_history": {"completed_imports": 5, "distinct_source_snapshots": 5,
                               "distinct_gameweek_cycles": 3},
        }},
        "host": {"offsite_backup": {
            "status": "configured", "configured": True, "encrypted": True,
            "external": True, "timer_active": True, "provider": "restic",
            "owner": "operator", "destination_fingerprint": "abcdef1234567890",
            "reasons": [],
        }},
    }


def _research() -> dict:
    return {
        "status": "passed", "measured_gameweeks": 3, "passing_gameweeks": 3,
        "policy": {"minimum_measured_gameweeks": 3},
    }


def _execution() -> dict:
    proven = {
        "contract": "implemented", "host_entrypoint_enabled": True,
        "autonomy_promoted": False, "observed_rehearsals": 3,
        "required_rehearsals": 3,
    }
    return {"browser_driver": {
        "captaincy": dict(proven), "lineup": dict(proven), "r3": dict(proven),
    }}


def _resilience() -> dict:
    return {"job_id": "job_drill", "status": "completed", "checks": 6,
            "passed": 6, "finished_at": "2026-08-30T22:00:00+00:00",
            "output_sha256": "a" * 64}


def _orchestration() -> dict:
    return {"job_id": "job_orchestration", "status": "completed", "checks": 12,
            "passed": 12, "finished_at": "2026-08-31T03:30:00+00:00",
            "output_sha256": "d" * 64}


def _alert_channel() -> dict:
    return {"schema": "mova-alert-channel-v1", "status": "configured",
            "configured": True, "external_delivery": True,
            "owner": "operator", "channel": "personal",
            "destination_fingerprint": "abcdef123456"}


def _alert_channel_drill() -> dict:
    return {"job_id": "job_alert", "status": "completed", "checks": 6,
            "passed": 6, "finished_at": "2026-08-31T04:00:00+00:00",
            "output_sha256": "e" * 64}


def _alert_channel_live() -> dict:
    return {"job_id": "job_alert_live", "status": "completed",
            "finished_at": "2026-08-31T04:30:00+00:00",
            "output_sha256": "f" * 64,
            "destination_fingerprint": "abcdef123456", "delivered": True,
            "external_calls": 1}


def _host_recovery() -> dict:
    return {
        "status": "completed", "completed": 5, "required": 5,
        "scenarios": {
            "api_recovery": {"status": "completed", "checks": 5, "passed": 5},
            "postgres_recovery": {"status": "completed", "checks": 8, "passed": 8},
            "browser_recovery": {"status": "completed", "checks": 9, "passed": 9},
            "combined_recovery": {"status": "completed", "checks": 13, "passed": 13},
            "reboot_recovery": {"status": "completed", "checks": 11, "passed": 11},
        },
    }


def _snapshot_rejection() -> dict:
    return {
        "job_id": "job_snapshot", "status": "completed", "checks": 10,
        "passed": 10, "finished_at": "2026-08-31T02:10:00+00:00",
        "output_sha256": "b" * 64,
    }


def _offsite_restore() -> dict:
    return {
        "job_id": "job_offsite_restore", "status": "completed", "checks": 8,
        "passed": 8, "finished_at": "2026-08-31T05:00:00+00:00",
        "output_sha256": "9" * 64,
    }


def _browser_failure() -> dict:
    return {
        "job_id": "job_browser_failure", "status": "completed", "checks": 11,
        "passed": 11, "finished_at": "2026-08-31T03:00:00+00:00",
        "output_sha256": "c" * 64,
    }


def test_readiness_separates_technical_eligibility_from_authority() -> None:
    report = evaluate_readiness(
        operator_status=_operator(), research_coverage=_research(),
        execution_status=_execution(), resilience_evidence=_resilience(),
        orchestration_evidence=_orchestration(),
        alert_channel=_alert_channel(),
        alert_channel_evidence=_alert_channel_drill(),
        alert_channel_live_evidence=_alert_channel_live(),
        host_recovery_evidence=_host_recovery(),
        offsite_restore_evidence=_offsite_restore(),
        snapshot_rejection_evidence=_snapshot_rejection(),
        browser_failure_evidence=_browser_failure(),
        generated_at="2026-08-30T22:00:00+00:00",
    )

    assert report["schema"] == "mova-autonomy-readiness-v1"
    assert report["overall_status"] == "ready"
    assert report["activation"]["technical_eligible_level"] == "A3"
    assert report["activation"]["current_action_level"] == "A0"
    assert report["activation"]["promotion_is_automatic"] is False
    assert "EXPLICIT_PROMOTION_REQUIRED" in report["activation"]["activation_blockers"]
    assert report["summary"] == {"pass": 25, "pending": 0, "blocked": 0, "total": 25}


def test_readiness_fails_closed_and_reports_specific_evidence_gaps() -> None:
    operator = deepcopy(_operator())
    operator["gameweek"]["readiness"] = "preliminary"
    operator["storage"]["postgres"]["import_history"]["distinct_gameweek_cycles"] = 1
    operator["host"]["offsite_backup"] = {
        "status": "unconfigured", "configured": False, "encrypted": False,
        "external": False, "timer_active": False,
    }
    research = deepcopy(_research())
    research.update(status="insufficient_gameweeks", measured_gameweeks=0,
                    passing_gameweeks=0)
    execution = _execution()
    execution["browser_driver"]["captaincy"]["observed_rehearsals"] = 0
    execution["browser_driver"]["lineup"].update(
        host_entrypoint_enabled=False, observed_rehearsals=0
    )
    execution["browser_driver"]["r3"].update(
        contract="missing", host_entrypoint_enabled=False, observed_rehearsals=0
    )

    report = evaluate_readiness(
        operator_status=operator, research_coverage=research,
        execution_status=execution, resilience_evidence={"status": "missing"},
        orchestration_evidence={"status": "missing"},
        alert_channel={"status": "local_only", "configured": False,
                       "external_delivery": False},
        alert_channel_evidence={"status": "missing"},
        alert_channel_live_evidence={"status": "missing"},
        host_recovery_evidence={"status": "incomplete", "completed": 0, "required": 5},
        offsite_restore_evidence={"status": "missing", "checks": 0, "passed": 0},
        snapshot_rejection_evidence={"status": "missing"},
        browser_failure_evidence={"status": "missing"},
    )
    by_code = {gate["code"]: gate for gate in report["gates"]}

    assert report["activation"]["technical_eligible_level"] == "A0"
    assert report["overall_status"] == "not_ready"
    assert by_code["GAMEWEEK_INPUTS_READY"]["status"] == "pending"
    assert by_code["RESEARCH_EVIDENCE_CALIBRATED"]["observed"]["measured_gameweeks"] == 0
    assert by_code["R3_DRIVER_PROVEN"]["status"] == "blocked"
    assert by_code["POSTGRES_THREE_GAMEWEEK_CYCLES"]["observed"] == 1
    assert by_code["POSTGRES_ROLE_SEPARATION"]["status"] == "pass"
    assert by_code["RESILIENCE_DRILL_PROVEN"]["status"] == "pending"
    assert by_code["ORCHESTRATION_DRILL_PROVEN"]["status"] == "pending"
    assert by_code["ALERT_CHANNEL_DRILL_PROVEN"]["status"] == "pending"
    assert by_code["EXTERNAL_ALERT_CHANNEL_CONFIGURED"]["status"] == "pending"
    assert by_code["EXTERNAL_ALERT_CHANNEL_LIVE_PROVEN"]["status"] == "pending"
    assert by_code["HOST_RECOVERY_DRILLS_PROVEN"]["status"] == "pending"
    assert by_code["OFF_HOST_BACKUP_CONFIGURED"]["status"] == "pending"
    assert by_code["OFF_HOST_RESTORE_PROVEN"]["status"] == "pending"
    assert by_code["SNAPSHOT_REJECTION_PROVEN"]["status"] == "pending"
    assert by_code["BROWSER_FAILURE_DRILL_PROVEN"]["status"] == "pending"
    assert all(item["next_action"] for item in report["next_actions"])


def test_readiness_cli_can_be_used_as_a_level_gate_and_metrics_are_bounded() -> None:
    parsed = parser().parse_args(["readiness", "--require-level", "A2"])
    assert parsed.command == "readiness" and parsed.require_level == "A2"
    report = evaluate_readiness(
        operator_status=_operator(), research_coverage=_research(),
        execution_status=_execution(), resilience_evidence=_resilience(),
        orchestration_evidence=_orchestration(),
        alert_channel=_alert_channel(),
        alert_channel_evidence=_alert_channel_drill(),
        alert_channel_live_evidence=_alert_channel_live(),
        host_recovery_evidence=_host_recovery(),
        offsite_restore_evidence=_offsite_restore(),
        snapshot_rejection_evidence=_snapshot_rejection(),
        browser_failure_evidence=_browser_failure(),
    )
    metrics = prometheus(report)
    assert 'mova_autonomy_technical_eligible_level{level="A3"} 1' in metrics
    assert 'mova_autonomy_readiness_gates{status="pass"} 25' in metrics
