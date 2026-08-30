"""Contrato puro entre ExecutionPlan y el proceso browser aislado.

No contiene cookies, CDP ni primitivas de escritura. El host sólo puede pasar
estos comandos tipados a un adapter que vuelva a validar plan, lease y DOM.
"""

from __future__ import annotations

import re

from mova_fpl.data.private_state import validate as validate_private_state


SCHEMA = "mova-browser-command-bundle-v1"
DOM_CONTRACT_VERSION = "fpl-pick-team-a11y-2026.08"
DOM_PROBE_SCHEMA = "mova-browser-dom-probe-v1"
UI_ACTION_PLAN_SCHEMA = "mova-browser-ui-action-plan-v1"


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


def plan_position_swaps(current: list[int], target: list[int]) -> list[dict]:
    """Produce la secuencia mínima y determinista de swaps por posición.

    Los índices son deliberadamente posicionales: el DOM conserva quince slots
    aunque cambie el jugador que ocupa cada uno. Nunca se usan refs efímeros.
    """
    observed = [int(value) for value in current]
    desired = [int(value) for value in target]
    if len(observed) != 15 or len(desired) != 15:
        raise ValueError("current y target deben contener exactamente 15 jugadores")
    if len(set(observed)) != 15 or set(observed) != set(desired):
        raise ValueError("current y target deben contener la misma plantilla sin duplicados")
    swaps = []
    for slot, expected in enumerate(desired):
        if observed[slot] == expected:
            continue
        other = observed.index(expected, slot + 1)
        swaps.append({
            "operation": "switch_slots",
            "first_position": slot + 1,
            "second_position": other + 1,
            "first_index": slot,
            "second_index": other,
            "selector": 'button[aria-label="Switch player"]',
        })
        observed[slot], observed[other] = observed[other], observed[slot]
    if observed != desired:
        raise AssertionError("la secuencia de swaps no reproduce el target")
    return [{**row, "sequence": index} for index, row in enumerate(swaps, start=1)]


def compile_r2_ui_action_plan(*, bundle: dict, pre_state: dict, dom_probe: dict,
                              expected_team_id: int) -> dict:
    """Liga command bundle, GET autenticado y DOM observado antes de tocar UI.

    El contrato de swaps quedó observado en producción. Captain/vice permanecen
    fail-closed hasta que FPL exponga controles semánticos estables y se capture
    una fixture verificable para ellos.
    """
    if bundle.get("schema") != SCHEMA or bundle.get("risk_class") != "R2":
        raise ValueError("command bundle R2 incompatible")
    normalized, quality = validate_private_state(
        pre_state, expected_team_id=expected_team_id,
    )
    if dom_probe.get("schema") != DOM_PROBE_SCHEMA:
        raise ValueError("DOM probe incompatible")
    if dom_probe.get("contract_version") != DOM_CONTRACT_VERSION:
        raise ValueError("versión del DOM probe incompatible")
    if dom_probe.get("status") != "pass":
        raise RuntimeError("DOM probe no superó el contrato fail-closed")
    slots = sorted(dom_probe.get("slots") or (), key=lambda row: int(row["position"]))
    observed = [int(row["element"]) for row in slots]
    current = [int(row["element"]) for row in normalized["picks"]]
    if len(slots) != 15 or observed != current:
        raise RuntimeError("el orden del DOM no coincide con el pre-state autenticado")

    set_lineup = next(
        row for row in bundle.get("commands") or () if row.get("operation") == "set_lineup"
    )
    target = [int(value) for value in set_lineup["starters"]] + [
        int(value) for value in set_lineup["bench_order"]
    ]
    swaps = plan_position_swaps(current, target)
    captain_now = next(
        int(row["element"]) for row in normalized["picks"] if row["is_captain"]
    )
    vice_now = next(
        int(row["element"]) for row in normalized["picks"] if row["is_vice_captain"]
    )
    captain_target = int(next(
        row for row in bundle["commands"] if row["operation"] == "set_captain"
    )["element"])
    vice_target = int(next(
        row for row in bundle["commands"] if row["operation"] == "set_vice_captain"
    )["element"])
    blockers = []
    if captain_now != captain_target:
        blockers.append("CAPTAIN_CONTROL_UNPROVEN")
    if vice_now != vice_target:
        blockers.append("VICE_CAPTAIN_CONTROL_UNPROVEN")
    return {
        "schema": UI_ACTION_PLAN_SCHEMA,
        "dom_contract_version": DOM_CONTRACT_VERSION,
        "execution_id": bundle.get("execution_id"),
        "plan_id": bundle.get("plan_id"),
        "pre_state_fingerprint": quality["fingerprint"],
        "status": "ready" if not blockers else "blocked",
        "blocking_codes": blockers,
        "target_order": target,
        "swaps": swaps,
        "captain": {"from": captain_now, "to": captain_target},
        "vice_captain": {"from": vice_now, "to": vice_target},
        "commit": {
            "selector": "button",
            "accessible_name": "Confirm My Choices",
            "max_clicks": 1,
            "enabled": not blockers,
        },
    }
