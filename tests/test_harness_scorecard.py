from mova_fpl.ops.harness_scorecard import evaluate_scorecard, prometheus


def _gate(code: str, status: str = "pass") -> dict:
    return {
        "code": code, "status": status,
        "next_action": None if status == "pass" else f"resolver {code}",
    }


def _readiness(*gates: dict) -> dict:
    return {
        "season": "2026-27", "cycle_id": "cycle_gw3", "gw": 3,
        "gates": list(gates),
        "activation": {
            "current_action_level": "A0", "technical_eligible_level": "A0",
            "writes_enabled": False, "activation_blockers": ["KILL_SWITCH_ON"],
        },
    }


def _cost(status: str = "within_budget") -> dict:
    scope_status = "exceeded" if status == "aggregate_exceeded" else "within_budget"
    return {
        "status": status,
        "gameweek": {"committed_tokens": 10, "token_limit": 100,
                     "remaining_tokens": 90, "committed_uses": 1,
                     "use_limit": 10, "remaining_uses": 9, "status": scope_status},
        "month": {"month": "2026-08", "committed_tokens": 20,
                  "token_limit": 1000, "remaining_tokens": 980,
                  "committed_uses": 2, "use_limit": 20,
                  "remaining_uses": 18, "status": scope_status},
        "semantic_reuse": {"gameweek_avoided_uses": 1, "month_avoided_uses": 2},
        "job_overruns": {"status": (
            "observed" if status == "job_overrun_observed" else "none"
        )},
        "orphaned_reservations": {"status": (
            "observed" if status == "orphaned_reservation_observed" else "none"
        )},
    }


def _improvement(with_learning: bool = True) -> dict:
    return {
        "proposal_counts": {"proposed": 1 if with_learning else 0,
                            "testing": 0, "accepted": 0, "rejected": 0},
        "lessons": [{"lesson_id": "lesson_1"}] if with_learning else [],
        "evaluations": [],
    }


def test_scorecard_groups_quality_cost_and_learning_without_granting_authority():
    report = evaluate_scorecard(
        readiness=_readiness(
            _gate("RUNTIME_HEALTHY"),
            _gate("RESEARCH_EVIDENCE_CALIBRATED", "pending"),
            _gate("CAPTAINCY_DRIVER_PROVEN", "pending"),
            _gate("POSTGRES_SHADOW_PARITY"),
            _gate("ALERT_CHANNEL_DRILL_PROVEN"),
            _gate("EXTERNAL_ALERT_CHANNEL_CONFIGURED", "pending"),
            _gate("EXTERNAL_ALERT_CHANNEL_LIVE_PROVEN", "pending"),
        ),
        cost_report=_cost(), improvement=_improvement(),
        deliberation={"status": "accepted", "provider": "codex"},
        generated_at="2026-08-31T03:00:00+00:00",
    )

    assert report["schema"] == "mova-harness-scorecard-v1"
    assert report["overall_status"] == "pending"
    assert report["quality"] == {
        "readiness_pass_ratio": 0.4286,
        "gates": {"pass": 3, "pending": 4, "blocked": 0, "total": 7},
        "technical_eligible_level": "A0",
    }
    assert report["authority"]["promotion_is_automatic"] is False
    assert report["authority"]["writes_enabled"] is False
    dimensions = {row["name"]: row for row in report["dimensions"]}
    assert dimensions["economics"]["status"] == "pass"
    assert dimensions["continuous_learning"]["status"] == "pass"
    assert dimensions["alerting"]["status"] == "pending"
    assert dimensions["agentic_decision"]["deliberation"]["terminal"] is True
    assert [item["code"] for item in report["next_actions"]] == [
        "RESEARCH_EVIDENCE_CALIBRATED", "CAPTAINCY_DRIVER_PROVEN",
        "EXTERNAL_ALERT_CHANNEL_CONFIGURED", "EXTERNAL_ALERT_CHANNEL_LIVE_PROVEN",
    ]


def test_scorecard_fails_closed_for_missing_deliberation_and_bad_budget():
    report = evaluate_scorecard(
        readiness=_readiness(_gate("STRATEGIC_MANIFEST_PRESENT")),
        cost_report=_cost("orphaned_reservation_observed"),
        improvement=_improvement(False), deliberation=None,
    )

    assert report["overall_status"] == "blocked"
    dimensions = {row["name"]: row for row in report["dimensions"]}
    assert dimensions["agentic_decision"]["status"] == "pending"
    assert dimensions["economics"]["status"] == "blocked"
    assert dimensions["continuous_learning"]["status"] == "pending"
    assert {item["code"] for item in report["next_actions"]} == {
        "TERMINAL_DELIBERATION_PRESENT", "AGENT_BUDGET_HEALTHY",
        "LEARNING_LOOP_OBSERVED",
    }


def test_historical_job_overrun_is_pending_but_aggregate_budget_stays_available():
    report = evaluate_scorecard(
        readiness=_readiness(_gate("RUNTIME_HEALTHY")),
        cost_report=_cost("job_overrun_observed"),
        improvement=_improvement(), deliberation={"status": "accepted"},
    )

    economics = next(row for row in report["dimensions"] if row["name"] == "economics")
    assert economics["status"] == "pending"
    assert economics["unmet"][0]["code"] == "AGENT_JOB_OVERRUN_REVIEWED"
    assert report["overall_status"] == "pending"


def test_reviewed_overrun_requests_followup_and_closed_overrun_passes():
    pending_cost = _cost()
    pending_cost["job_overruns"] = {"status": "reviewed_pending"}
    pending = evaluate_scorecard(
        readiness=_readiness(_gate("RUNTIME_HEALTHY")), cost_report=pending_cost,
        improvement=_improvement(), deliberation={"status": "accepted"},
    )
    economics = next(row for row in pending["dimensions"] if row["name"] == "economics")
    assert economics["unmet"][0]["code"] == "AGENT_JOB_OVERRUN_FOLLOWUP_VERIFIED"

    closed_cost = _cost()
    closed_cost["job_overruns"] = {"status": "closed"}
    closed = evaluate_scorecard(
        readiness=_readiness(_gate("RUNTIME_HEALTHY")), cost_report=closed_cost,
        improvement=_improvement(), deliberation={"status": "accepted"},
    )
    economics = next(row for row in closed["dimensions"] if row["name"] == "economics")
    assert economics["status"] == "pass"


def test_scorecard_prometheus_has_bounded_labels():
    report = evaluate_scorecard(
        readiness=_readiness(_gate("RUNTIME_HEALTHY")),
        cost_report=_cost(), improvement=_improvement(),
        deliberation={"status": "accepted"},
    )
    metrics = prometheus(report)

    assert "mova_harness_scorecard_up 1" in metrics
    assert 'mova_harness_scorecard_status{status="pass"} 1' in metrics
    assert "mova_harness_readiness_pass_ratio 1.0000" in metrics
    assert "cycle_gw3" not in metrics
