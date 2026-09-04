"""Contrato puro entre ExecutionPlan y el proceso browser aislado.

No contiene cookies, CDP ni primitivas de escritura. El host sólo puede pasar
estos comandos tipados a un adapter que vuelva a validar plan, lease y DOM.
"""

from __future__ import annotations

import re

from mova_fpl.data.private_state import validate as validate_private_state


SCHEMA = "mova-browser-command-bundle-v1"
DOM_CONTRACT_VERSION = "fpl-pick-team-a11y-2026.09.1"
DOM_PROBE_SCHEMA = "mova-browser-dom-probe-v1"
UI_ACTION_PLAN_SCHEMA = "mova-browser-ui-action-plan-v1"
TRANSFER_DOM_CONTRACT_VERSION = "fpl-transfers-a11y-2026.09.1"
TRANSFER_DOM_PROBE_SCHEMA = "mova-browser-transfer-dom-probe-v1"
R3_UI_ACTION_PLAN_SCHEMA = "mova-browser-r3-ui-action-plan-v1"

CHIP_PRIVATE_NAMES = {
    "wildcard": "wildcard", "free_hit": "freehit",
    "bench_boost": "bboost", "triple_captain": "3xc",
}
CHIP_CONTROLS = {
    "wildcard": ("transfers", "Wildcard Play"),
    "free_hit": ("transfers", "Free Hit Play"),
    "bench_boost": ("pick_team", "Bench Boost Play"),
    "triple_captain": ("pick_team", "Triple Captain Play"),
}


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
    risk_class = action.get("risk_class")
    if risk_class not in {"R2", "R3"}:
        raise NotImplementedError("el adapter browser sólo compila acciones R2/R3")
    diff = action["exact_diff"]
    commands = [{"sequence": 1, "operation": "read_private_pre_state"}]
    if risk_class == "R3":
        commands.extend([
            {"sequence": 2, "operation": "open_transfers"},
            {
                "sequence": 3, "operation": "stage_exact_transfers",
                "out": [int(value) for value in diff["transfers"]["out"]],
                "in": [int(value) for value in diff["transfers"]["in"]],
                "hits": int(diff["transfers"]["hits"]),
            },
            {"sequence": 4, "operation": "stage_chip",
             "chip": diff["chip"]["to"]},
            {"sequence": 5, "operation": "verify_transfer_preview"},
            {"sequence": 6, "operation": "commit_irreversible_once"},
        ])
        offset = 5
    else:
        offset = 0
    commands.extend([
        {
            "sequence": 2 + offset, "operation": "set_lineup",
            "starters": [int(value) for value in diff["lineup"]["starters"]],
            "bench_order": [int(value) for value in diff["lineup"]["bench_order"]],
        },
        {"sequence": 3 + offset, "operation": "set_captain",
         "element": int(diff["captain"]["to"])},
        {"sequence": 4 + offset, "operation": "set_vice_captain",
         "element": int(diff["vice_captain"]["to"])},
        {"sequence": 5 + offset, "operation": "commit_team_once"},
        {"sequence": 6 + offset, "operation": "reload_pick_team"},
        {"sequence": 7 + offset, "operation": "read_private_post_state"},
    ])
    return {
        "schema": SCHEMA,
        "dom_contract_version": DOM_CONTRACT_VERSION,
        "plan_id": plan["plan_id"],
        "plan_sha256": plan["content_sha256"],
        "cycle_id": plan["cycle_id"],
        "risk_class": risk_class,
        "expected_pre_fingerprint": action["expected_pre_team_fingerprint"],
        "expected_post_fingerprint": action["expected_post_decision_fingerprint"],
        "commands": commands,
        "failure_policy": {
            "before_commit": "fail_without_retry",
            "at_or_after_commit": "ambiguous_stop_and_reconcile",
            "before_first_commit": "fail_without_retry",
            "at_or_after_first_commit": "ambiguous_stop_and_reconcile",
            "success": "post_reload_exact_match_only",
            "retry_after_commit": False,
            "max_irreversible_confirmations": 1 if risk_class == "R3" else 0,
            "max_reversible_team_commits": 1,
        },
    }


def assess_transfers_snapshot(snapshot: str) -> dict:
    """Evalúa la superficie R3 observada sin seleccionar ni confirmar nada."""
    required = {
        "transfers": 'heading "Transfers"',
        "deadline": 'heading "Deadline:',
        "signed_in": 'link "Sign Out"',
        "wildcard": 'button "Wildcard Play"',
        "free_hit": 'button "Free Hit Play"',
        "make_transfers": 'button "Make Transfers"',
        "player_search": 'searchbox "Find a player"',
        "budget": 'heading "Budget"',
        "free_transfers": 'heading "Free transfers"',
        "cost": 'heading "Cost"',
    }
    checks = {name: token in snapshot for name, token in required.items()}
    remove_controls = len(re.findall(r'button "Remove player(?: [^"]*)?"', snapshot))
    # La vista pitch y la tabla de mercado pueden exponer controles duplicados
    # para jugadores propios. Quince es el mínimo de plantilla, no un total DOM.
    checks["squad_remove_controls_present"] = remove_controls >= 15
    deadline_match = re.search(r'heading "Deadline: ([^"]+)"', snapshot)
    return {
        "schema": "mova-browser-transfer-dom-assessment-v1",
        "contract_version": TRANSFER_DOM_CONTRACT_VERSION,
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
        "remove_player_controls": remove_controls,
        "deadline_label": deadline_match.group(1) if deadline_match else None,
    }


def compile_r3_ui_action_plan(*, bundle: dict, pre_state: dict, dom_probe: dict,
                              expected_team_id: int) -> dict:
    """Liga una intención R3 con estado privado y un probe allowlisted.

    El resultado es un contrato de rehearsal: no contiene CDP, cookies ni una
    primitiva ejecutable y su entrypoint de producción permanece deshabilitado.
    """
    if bundle.get("schema") != SCHEMA or bundle.get("risk_class") != "R3":
        raise ValueError("command bundle R3 incompatible")
    normalized, quality = validate_private_state(
        pre_state, expected_team_id=expected_team_id,
    )
    if (
        dom_probe.get("schema") != TRANSFER_DOM_PROBE_SCHEMA
        or dom_probe.get("contract_version") != TRANSFER_DOM_CONTRACT_VERSION
    ):
        raise ValueError("DOM probe de transfers incompatible")
    if dom_probe.get("status") != "pass":
        raise RuntimeError("DOM probe de transfers no superó el contrato fail-closed")

    stage = next(row for row in bundle.get("commands") or ()
                 if row.get("operation") == "stage_exact_transfers")
    chip_command = next(row for row in bundle.get("commands") or ()
                        if row.get("operation") == "stage_chip")
    outgoing = [int(value) for value in stage.get("out") or ()]
    incoming = [int(value) for value in stage.get("in") or ()]
    chip = chip_command.get("chip")
    blockers: list[str] = []
    if len(outgoing) != len(incoming) or not outgoing and not chip:
        blockers.append("R3_INTENT_EMPTY_OR_UNPAIRED")
    if len(set(outgoing)) != len(outgoing) or len(set(incoming)) != len(incoming):
        blockers.append("R3_TRANSFER_DUPLICATE")

    picks = {int(row["element"]): row for row in normalized["picks"]}
    squad_rows = {int(row["element"]): row for row in dom_probe.get("squad") or ()}
    market_rows = {int(row["element"]): row for row in dom_probe.get("targets") or ()}
    if set(squad_rows) != set(picks):
        raise RuntimeError("plantilla del DOM R3 no coincide con el pre-state autenticado")
    if any(element not in picks for element in outgoing):
        blockers.append("TRANSFER_OUT_NOT_OWNED")
    if any(element in picks or element not in market_rows for element in incoming):
        blockers.append("TRANSFER_IN_IDENTITY_UNPROVEN")

    actions = []
    final_types = [int(row["element_type"]) for row in normalized["picks"]
                   if int(row["element"]) not in outgoing]
    spend = 0
    proceeds = 0
    for sequence, (element_out, element_in) in enumerate(zip(outgoing, incoming), start=1):
        out_row = picks.get(element_out) or {}
        in_row = market_rows.get(element_in) or {}
        if int(out_row.get("element_type", 0)) != int(in_row.get("element_type", -1)):
            blockers.append("TRANSFER_POSITION_MISMATCH")
        price = int(in_row.get("price", 0))
        if not 30 <= price <= 200 or not str(in_row.get("web_name") or "").strip():
            blockers.append("TRANSFER_TARGET_METADATA_INVALID")
        spend += price
        proceeds += int(out_row.get("selling_price", 0))
        final_types.append(int(in_row.get("element_type", 0)))
        actions.append({
            "sequence": sequence, "operation": "replace_player",
            "out": {
                "element": element_out,
                "position": int(out_row.get("position", 0)),
                "web_name": squad_rows.get(element_out, {}).get("web_name"),
                "selector": 'button[aria-label^="Remove player"]',
            },
            "in": {
                "element": element_in, "element_type": int(in_row.get("element_type", 0)),
                "web_name": in_row.get("web_name"), "team": in_row.get("team"),
                "price": price, "searchbox_name": "Find a player",
                "selector": 'button[aria-label^="Add player"]',
            },
        })
    if sorted(final_types) != [1, 1, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 4, 4, 4]:
        blockers.append("FINAL_POSITION_QUOTAS_INVALID")

    bank_before = int(normalized["transfers"]["bank"])
    bank_after = bank_before + proceeds - spend
    if bank_after < 0:
        blockers.append("TRANSFER_BUDGET_NEGATIVE")
    free = max(0, min(5, int(normalized["transfers"]["limit"])
                      - int(normalized["transfers"]["made"])))
    expected_hits = 0 if chip in {"wildcard", "free_hit"} else max(0, len(incoming) - free)
    if int(stage.get("hits") or 0) != expected_hits:
        blockers.append("TRANSFER_HIT_ACCOUNTING_MISMATCH")

    chip_action = None
    if chip:
        if chip not in CHIP_PRIVATE_NAMES or chip not in CHIP_CONTROLS:
            blockers.append("CHIP_UNKNOWN")
        else:
            private_name = CHIP_PRIVATE_NAMES[chip]
            availability = {row["name"]: row["status_for_entry"]
                            for row in normalized["chips"]}
            if availability.get(private_name) != "available":
                blockers.append("CHIP_NOT_AVAILABLE")
            route, accessible_name = CHIP_CONTROLS[chip]
            chip_action = {
                "operation": "stage_chip", "chip": chip, "route": route,
                "selector": "button", "accessible_name": accessible_name,
                "max_clicks": 1,
            }

    controls = dom_probe.get("controls") or {}
    required_controls = {
        "make_transfers": "Make Transfers", "player_search": "Find a player",
    }
    if any(controls.get(key) != value for key, value in required_controls.items()):
        blockers.append("TRANSFER_CONTROLS_UNPROVEN")
    if chip_action and chip_action["route"] == "transfers":
        chip_buttons = controls.get("chip_buttons") or []
        if chip_action["accessible_name"] not in chip_buttons:
            blockers.append("CHIP_CONTROL_UNPROVEN")

    return {
        "schema": R3_UI_ACTION_PLAN_SCHEMA,
        "dom_contract_version": TRANSFER_DOM_CONTRACT_VERSION,
        "execution_id": bundle.get("execution_id"), "plan_id": bundle.get("plan_id"),
        "pre_state_fingerprint": quality["fingerprint"],
        "status": "ready" if not blockers else "blocked",
        "blocking_codes": sorted(set(blockers)),
        "scope": "transfers_and_chip" if chip and actions else
                 "chip_only" if chip else "transfers_only",
        "transfers": actions,
        "economics": {
            "bank_before": bank_before, "sale_proceeds": proceeds,
            "purchase_cost": spend, "bank_after": bank_after,
            "free_transfers": free, "expected_hits": expected_hits,
        },
        "chip": chip_action,
        "preview": {
            "required": True, "exact_transfer_count": len(actions),
            "expected_hits": expected_hits, "expected_bank_after": bank_after,
            "expected_chip": chip,
        },
        "commit": {
            "selector": "button", "accessible_name": "Make Transfers",
            "confirmation_required": True, "max_stage_clicks": 1,
            "max_confirmation_clicks": 1, "enabled": not blockers,
        },
        "failure_policy": bundle.get("failure_policy"),
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

    El contrato de swaps y los checkboxes semánticos Captain/Vice Captain fueron
    observados en producción. Cualquier ausencia o discrepancia queda fail-closed.
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
    labels_by_element = {
        int(row["element"]): str(row.get("web_name") or "").strip()
        for row in slots
    }
    target_slots = [
        {
            "position": position,
            "element": element,
            "web_name": labels_by_element.get(element) or None,
        }
        for position, element in enumerate(target, start=1)
    ]
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
    if captain_target == vice_target:
        raise ValueError("capitán y vicecapitán deben ser jugadores diferentes")

    controls = dom_probe.get("captain_controls") or {}
    control_rows = controls.get("starters") or []
    controls_by_element = {int(row["element"]): row for row in control_rows}
    if controls.get("status") == "pass":
        checked_captains = [
            int(row["element"]) for row in control_rows if row.get("captain_checked")
        ]
        checked_vices = [
            int(row["element"]) for row in control_rows if row.get("vice_captain_checked")
        ]
        if checked_captains != [captain_now] or checked_vices != [vice_now]:
            raise RuntimeError("los controles Captain/Vice no coinciden con el pre-state")

    def semantic_action(*, target: int, accessible_name: str) -> dict | None:
        row = controls_by_element.get(target)
        if controls.get("status") != "pass" or not row:
            return None
        if not row.get("captain_checkbox") or not row.get("vice_captain_checkbox"):
            return None
        position = int(row["position"])
        if position > 11:
            return None
        return {
            "operation": "set_player_checkbox",
            "target_position": position,
            "player_button_index": int(row["player_button_index"]),
            "player_selector": 'button[data-pitch-element="true"]',
            "checkbox_role": "checkbox",
            "checkbox_accessible_name": accessible_name,
            "expected_checked_after": True,
        }

    blockers = []
    if swaps and any(not row["web_name"] for row in target_slots):
        blockers.append("LINEUP_LABELS_UNPROVEN")
    captain_action = None
    vice_action = None
    if captain_now != captain_target:
        captain_action = semantic_action(target=captain_target, accessible_name="Captain")
        if captain_action is None:
            blockers.append("CAPTAIN_CONTROL_UNPROVEN")
    if vice_now != vice_target:
        vice_action = semantic_action(
            target=vice_target, accessible_name="Vice Captain",
        )
        if vice_action is None:
            blockers.append("VICE_CAPTAIN_CONTROL_UNPROVEN")
    return {
        "schema": UI_ACTION_PLAN_SCHEMA,
        "dom_contract_version": DOM_CONTRACT_VERSION,
        "execution_id": bundle.get("execution_id"),
        "plan_id": bundle.get("plan_id"),
        "pre_state_fingerprint": quality["fingerprint"],
        "status": "ready" if not blockers else "blocked",
        "blocking_codes": blockers,
        "lineup": {
            "from_order": current,
            "to_order": target,
            "target_slots": target_slots,
            "swap_count": len(swaps),
        },
        "target_order": target,
        "swaps": swaps,
        "captain": {
            "from": captain_now, "to": captain_target, "action": captain_action,
        },
        "vice_captain": {
            "from": vice_now, "to": vice_target, "action": vice_action,
        },
        "commit": {
            "selector": "button",
            "accessible_name": "Confirm My Choices",
            "max_clicks": 1,
            "enabled": not blockers,
        },
    }
