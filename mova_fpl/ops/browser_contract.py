"""Contrato puro entre ExecutionPlan y el proceso browser aislado.

No contiene cookies, CDP ni primitivas de escritura. El host sólo puede pasar
estos comandos tipados a un adapter que vuelva a validar plan, lease y DOM.
"""

from __future__ import annotations

import re


SCHEMA = "mova-browser-command-bundle-v1"
DOM_CONTRACT_VERSION = "fpl-pick-team-a11y-2026.08"


def assess_pick_team_snapshot(snapshot: str) -> dict:
    """Evalúa un snapshot accessibility sanitizado sin depender de refs efímeros."""
    required = {
        "pick_team": 'heading "Pick Team"',
        "deadline": 'heading "Deadline:',
        "signed_in": 'link "Sign Out"',
        "transfers": 'link "Transfers"',
        "bench_boost": 'button "Bench Boost Play"',
        "triple_captain": 'button "Triple Captain Play"',
        "wildcard": 'button "Wildcard Play"',
        "free_hit": 'button "Free Hit Play"',
    }
    checks = {name: token in snapshot for name, token in required.items()}
    switch_players = len(re.findall(r'button "Switch player"', snapshot))
    deadline_match = re.search(r'heading "Deadline: ([^"]+)"', snapshot)
    checks["fifteen_switch_controls"] = switch_players == 15
    return {
        "schema": "mova-browser-dom-assessment-v1",
        "contract_version": DOM_CONTRACT_VERSION,
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
        "switch_player_controls": switch_players,
        "deadline_label": deadline_match.group(1) if deadline_match else None,
    }


def compile_browser_commands(plan: dict) -> dict:
    """Compila intención determinista; el adapter nunca recibe prosa del agente."""
    authorization = plan.get("authorization") or {}
    action = plan.get("action") or {}
    if authorization.get("status") != "authorized" or not authorization.get("authorized"):
        raise ValueError("sólo un ExecutionPlan autorizado es compilable")
    if action.get("risk_class") != "R2":
        raise NotImplementedError(
            "adapter browser actual admite sólo R2; transfers/chips R3 siguen fail-closed"
        )
    diff = action["exact_diff"]
    commands = [
        {"sequence": 1, "operation": "read_private_pre_state"},
        {
            "sequence": 2, "operation": "set_lineup",
            "starters": [int(value) for value in diff["lineup"]["starters"]],
            "bench_order": [int(value) for value in diff["lineup"]["bench_order"]],
        },
        {"sequence": 3, "operation": "set_captain",
         "element": int(diff["captain"]["to"])},
        {"sequence": 4, "operation": "set_vice_captain",
         "element": int(diff["vice_captain"]["to"])},
        {"sequence": 5, "operation": "commit_team_once"},
        {"sequence": 6, "operation": "reload_pick_team"},
        {"sequence": 7, "operation": "read_private_post_state"},
    ]
    return {
        "schema": SCHEMA,
        "dom_contract_version": DOM_CONTRACT_VERSION,
        "plan_id": plan["plan_id"],
        "plan_sha256": plan["content_sha256"],
        "cycle_id": plan["cycle_id"],
        "risk_class": "R2",
        "expected_pre_fingerprint": action["expected_pre_team_fingerprint"],
        "expected_post_fingerprint": action["expected_post_decision_fingerprint"],
        "commands": commands,
        "failure_policy": {
            "before_commit": "fail_without_retry",
            "at_or_after_commit": "ambiguous_stop_and_reconcile",
            "success": "post_reload_exact_match_only",
        },
    }
