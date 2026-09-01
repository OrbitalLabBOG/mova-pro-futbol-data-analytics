from __future__ import annotations

import json

from mova_fpl.ops.api import _dashboard
from mova_fpl.ops.cli import parser
from mova_fpl.ops.cockpit import evaluate_cockpit, render_cockpit


def _inputs() -> dict:
    operator = {
        "overall_status": "healthy",
        "gameweek": {
            "gw": 3, "cycle_id": "cycle-3", "deadline_at": "2026-09-04T17:30:00Z",
            "seconds_to_deadline": 7200, "phase": "final", "readiness": "ready",
        },
        "runtime": {"git_sha": "abc123", "controls": {
            "mode": "shadow", "action_level": "A0", "kill_switch": True,
            "browser_writes": False,
        }},
        "operations": {
            "open_incidents": [], "latest_tick": {"status": "completed"},
            "failed_jobs_last_24h": [],
        },
        "host": {"systemd": {
            name: {"active_state": "active"} for name in (
                "mova-fpl-collector.timer", "mova-fpl-analytics.timer",
                "mova-fpl-research.timer", "mova-fpl-backup.timer",
            )
        }},
        "data": {"service": {"status": "healthy"}},
        "analytics": {"status": "healthy"},
        "storage": {"postgres_role": "shadow", "postgres": {
            "status": "healthy", "read_parity": {"status": "pass"},
        }},
        "research": {"service_status": "healthy"},
        "deliberation": {"status": "accepted"},
    }
    workflow = {
        "verdict": "safe_to_wait", "violations": [],
        "stages": [
            {"name": name, "owner": "fixture", "status": status,
             "outcome": "ok", "subject_id": name, "next_action": None}
            for name, status in (
                ("observe", "complete"), ("contextualize", "complete"),
                ("research", "complete"), ("propose_validate", "complete"),
                ("deliberate", "complete"), ("preflight", "complete"),
                ("execute_verify", "skipped_policy"), ("settle", "not_due"),
                ("review_learn", "not_due"),
            )
        ],
    }
    return {
        "operator_status": operator,
        "safety": {"verdict": "safe_to_wait"},
        "readiness": {"activation": {
            "current_action_level": "A0", "technical_eligible_level": "A0",
            "writes_enabled": False,
        }},
        "scorecard": {"overall_status": "pending", "quality": {
            "readiness_pass_ratio": 0.64,
        }},
        "workflow": workflow,
        "costs": {
            "status": "ok",
            "gameweek": {"committed_tokens": 100, "token_limit": 1000,
                         "remaining_tokens": 900, "committed_uses": 2,
                         "use_limit": 20, "remaining_uses": 18, "status": "within_budget"},
            "month": {"month": "2026-09", "committed_tokens": 100,
                      "token_limit": 3000, "remaining_tokens": 2900,
                      "committed_uses": 2, "use_limit": 60,
                      "remaining_uses": 58, "status": "within_budget"},
        },
        "alert_channel": {"status": "configured", "configured": True,
                          "external_delivery": True, "channel": "ops"},
        "alert_status": {"due": 0},
        "generated_at": "2026-09-01T20:00:00+00:00",
    }


def test_cockpit_contract_is_shared_sanitized_and_read_only():
    payload = evaluate_cockpit(**_inputs())

    assert payload["schema"] == "mova-cockpit-v1"
    assert payload["verdict"] == "healthy"
    assert payload["authority"]["current_action_level"] == "A0"
    assert payload["authority"]["writes_enabled"] is False
    assert payload["runtime_mutated"] is False
    assert len(payload["functions"]) == 8
    functions = {row["code"]: row for row in payload["functions"]}
    assert functions["research"]["status"] == "healthy"
    assert functions["backup"]["status"] == "active_local"
    assert payload["economics"]["gameweek"]["remaining_uses"] == 18
    assert "url" not in json.dumps(payload).lower()
    assert "MOVA COCKPIT · HEALTHY" in render_cockpit(payload)


def test_cockpit_surfaces_critical_incident_and_budget_without_enabling_writes():
    values = _inputs()
    values["operator_status"]["operations"]["open_incidents"] = [{
        "incident_id": "incident_test", "severity": "P0", "status": "open",
        "title": "Scheduler heartbeat unhealthy",
    }]
    values["costs"]["gameweek"]["remaining_uses"] = 1
    payload = evaluate_cockpit(**values)

    assert payload["verdict"] == "critical"
    assert payload["alerts"]["items"][0]["incident_id"] == "incident_test"
    assert any(row["code"] == "AGENT_BUDGET_LOW"
               for row in payload["alerts"]["items"])
    assert payload["authority"]["writes_enabled"] is False


def test_dashboard_renders_action_center_and_machine_links():
    page = _dashboard(evaluate_cockpit(**_inputs())).decode()

    assert "MOVA Fantasy Fútbol" in page
    assert "Ciclo agentic" in page
    assert "Funciones y activaciones" in page
    assert "/api/v1/cockpit" in page
    assert "solo lectura" in page


def test_cli_exposes_cockpit_watch_and_incident_triage():
    cockpit = parser().parse_args(["cockpit", "--json", "--watch", "30"])
    assert cockpit.command == "cockpit"
    assert cockpit.as_json is True
    assert cockpit.watch == 30
    triage = parser().parse_args([
        "triage", "--incident-id", "incident_test", "--json",
    ])
    assert triage.command == "triage"
    assert triage.incident_id == "incident_test"
