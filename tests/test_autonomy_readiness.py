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


def test_readiness_separates_technical_eligibility_from_authority() -> None:
    report = evaluate_readiness(
        operator_status=_operator(), research_coverage=_research(),
        execution_status=_execution(), generated_at="2026-08-30T22:00:00+00:00",
    )

    assert report["schema"] == "mova-autonomy-readiness-v1"
    assert report["overall_status"] == "ready"
    assert report["activation"]["technical_eligible_level"] == "A3"
    assert report["activation"]["current_action_level"] == "A0"
    assert report["activation"]["promotion_is_automatic"] is False
    assert "EXPLICIT_PROMOTION_REQUIRED" in report["activation"]["activation_blockers"]
    assert report["summary"] == {"pass": 15, "pending": 0, "blocked": 0, "total": 15}


def test_readiness_fails_closed_and_reports_specific_evidence_gaps() -> None:
    operator = deepcopy(_operator())
    operator["gameweek"]["readiness"] = "preliminary"
    operator["storage"]["postgres"]["import_history"]["distinct_gameweek_cycles"] = 1
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
        execution_status=execution,
    )
    by_code = {gate["code"]: gate for gate in report["gates"]}

    assert report["activation"]["technical_eligible_level"] == "A0"
    assert report["overall_status"] == "not_ready"
    assert by_code["GAMEWEEK_INPUTS_READY"]["status"] == "pending"
    assert by_code["RESEARCH_EVIDENCE_CALIBRATED"]["observed"]["measured_gameweeks"] == 0
    assert by_code["R3_DRIVER_PROVEN"]["status"] == "blocked"
    assert by_code["POSTGRES_THREE_GAMEWEEK_CYCLES"]["observed"] == 1
    assert by_code["POSTGRES_ROLE_SEPARATION"]["status"] == "pass"
    assert all(item["next_action"] for item in report["next_actions"])


def test_readiness_cli_can_be_used_as_a_level_gate_and_metrics_are_bounded() -> None:
    parsed = parser().parse_args(["readiness", "--require-level", "A2"])
    assert parsed.command == "readiness" and parsed.require_level == "A2"
    report = evaluate_readiness(
        operator_status=_operator(), research_coverage=_research(),
        execution_status=_execution(),
    )
    metrics = prometheus(report)
    assert 'mova_autonomy_technical_eligible_level{level="A3"} 1' in metrics
    assert 'mova_autonomy_readiness_gates{status="pass"} 15' in metrics
