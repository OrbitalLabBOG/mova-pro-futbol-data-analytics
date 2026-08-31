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
    scope_status = "exceeded" if status != "within_budget" else "within_budget"
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
        ),
        cost_report=_cost(), improvement=_improvement(),
        deliberation={"status": "accepted", "provider": "codex"},
        generated_at="2026-08-31T03:00:00+00:00",
    )

    assert report["schema"] == "mova-harness-scorecard-v1"
    assert report["overall_status"] == "pending"
    assert report["quality"] == {
        "readiness_pass_ratio": 0.5,
        "gates": {"pass": 2, "pending": 2, "blocked": 0, "total": 4},
        "technical_eligible_level": "A0",
    }
    assert report["authority"]["promotion_is_automatic"] is False
    assert report["authority"]["writes_enabled"] is False
    dimensions = {row["name"]: row for row in report["dimensions"]}
    assert dimensions["economics"]["status"] == "pass"
    assert dimensions["continuous_learning"]["status"] == "pass"
    assert dimensions["agentic_decision"]["deliberation"]["terminal"] is True
    assert [item["code"] for item in report["next_actions"]] == [
        "RESEARCH_EVIDENCE_CALIBRATED", "CAPTAINCY_DRIVER_PROVEN",
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
