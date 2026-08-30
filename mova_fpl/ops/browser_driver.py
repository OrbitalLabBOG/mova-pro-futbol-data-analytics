"""Typed host-driver contract for reversible FPL browser actions.

This module is deliberately free of CDP and subprocess primitives.  It turns a
validated UI action plan into a small instruction stream that the host adapter
can execute.  Lineup swaps have a fully typed, testable instruction stream but
remain gated until their live interaction has been rehearsed; captain and
vice-captain use the semantic controls already observed in production.
"""

from __future__ import annotations

from dataclasses import dataclass

from mova_fpl.ops.browser_contract import R3_UI_ACTION_PLAN_SCHEMA, UI_ACTION_PLAN_SCHEMA


DRIVER_PLAN_SCHEMA = "mova-browser-r2-driver-plan-v1"
DRIVER_CONTRACT_VERSION = "fpl-r2-host-driver-2026.08.2"
R3_DRIVER_PLAN_SCHEMA = "mova-browser-r3-driver-plan-v1"
R3_DRIVER_CONTRACT_VERSION = "fpl-r3-host-driver-2026.08.1"
LINEUP_EXECUTION_PROMOTED = False


def driver_capabilities() -> dict:
    """Public, secret-free capability ledger for status and operator tooling."""
    return {
        "schema": "mova-browser-driver-capabilities-v1",
        "contract_version": DRIVER_CONTRACT_VERSION,
        "captaincy": {
            "contract": "implemented", "host_entrypoint_enabled": True,
            "autonomy_promoted": False, "observed_rehearsals": 0,
            "required_rehearsals": 3,
        },
        "lineup": {
            "contract": "implemented",
            "host_entrypoint_enabled": LINEUP_EXECUTION_PROMOTED,
            "autonomy_promoted": False, "observed_rehearsals": 0,
            "required_rehearsals": 3,
        },
        "r3": {
            "contract": "implemented", "host_entrypoint_enabled": False,
            "autonomy_promoted": False, "observed_rehearsals": 0,
            "required_rehearsals": 3,
        },
    }


class DriverPlanBlocked(RuntimeError):
    """A UI plan cannot be materialized by the currently promoted driver."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code


@dataclass(frozen=True)
class DriverStep:
    sequence: int
    operation: str
    detail: dict

    def as_dict(self) -> dict:
        return {
            "sequence": self.sequence,
            "operation": self.operation,
            **self.detail,
        }


def _semantic_steps(section: dict, *, role: str, start: int) -> list[DriverStep]:
    action = section.get("action")
    if action is None:
        return []
    expected_name = "Captain" if role == "captain" else "Vice Captain"
    if (
        action.get("operation") != "set_player_checkbox"
        or action.get("player_selector") != 'button[data-pitch-element="true"]'
        or action.get("checkbox_role") != "checkbox"
        or action.get("checkbox_accessible_name") != expected_name
        or action.get("expected_checked_after") is not True
    ):
        raise DriverPlanBlocked(
            "SEMANTIC_CONTROL_INVALID",
            f"acción semántica inválida para {role}",
        )
    index = int(action.get("player_button_index", -1))
    position = int(action.get("target_position", 0))
    if not 0 <= index < 11 or position != index + 1:
        raise DriverPlanBlocked(
            "PLAYER_CONTROL_INDEX_INVALID",
            f"índice posicional inválido para {role}",
        )
    element = int(section["to"])
    return [
        DriverStep(start, "open_player_sheet", {
            "role": role, "element": element, "player_button_index": index,
            "selector": action["player_selector"],
        }),
        DriverStep(start + 1, "focus_checkbox", {
            "role": role, "accessible_name": expected_name,
        }),
        DriverStep(start + 2, "press_space", {"role": role}),
        DriverStep(start + 3, "verify_checkbox", {
            "role": role, "accessible_name": expected_name,
            "expected_checked": True,
        }),
        DriverStep(start + 4, "close_player_sheet", {"role": role}),
    ]


def _lineup_steps(ui_plan: dict, *, start: int) -> list[DriverStep]:
    swaps = ui_plan.get("swaps") or []
    if not swaps:
        return []
    lineup = ui_plan.get("lineup") or {}
    current = [int(value) for value in lineup.get("from_order") or ()]
    target = [int(value) for value in lineup.get("to_order") or ()]
    target_slots = lineup.get("target_slots") or []
    if (
        len(current) != 15 or len(target) != 15
        or len(set(current)) != 15 or set(current) != set(target)
        or int(lineup.get("swap_count", -1)) != len(swaps)
        or len(target_slots) != 15
    ):
        raise DriverPlanBlocked(
            "LINEUP_CONTRACT_INVALID", "contrato posicional de XI/banca inválido",
        )
    labels = []
    for position, (element, row) in enumerate(zip(target, target_slots), start=1):
        label = str(row.get("web_name") or "").strip()
        if (
            int(row.get("position", 0)) != position
            or int(row.get("element", 0)) != element
            or not label or len(label) > 80
        ):
            raise DriverPlanBlocked(
                "LINEUP_TARGET_LABEL_INVALID",
                f"slot target {position} no tiene identidad visual demostrable",
            )
        labels.append({"position": position, "element": element, "web_name": label})

    simulated = current[:]
    steps: list[DriverStep] = []
    for expected_sequence, swap in enumerate(swaps, start=1):
        left = int(swap.get("first_index", -1))
        right = int(swap.get("second_index", -1))
        if (
            swap.get("operation") != "switch_slots"
            or int(swap.get("sequence", 0)) != expected_sequence
            or swap.get("selector") != 'button[aria-label="Switch player"]'
            or not 0 <= left < 15 or not 0 <= right < 15 or left == right
            or int(swap.get("first_position", 0)) != left + 1
            or int(swap.get("second_position", 0)) != right + 1
        ):
            raise DriverPlanBlocked(
                "LINEUP_SWAP_INVALID", f"swap {expected_sequence} no cumple el contrato",
            )
        steps.extend([
            DriverStep(start + len(steps), "select_swap_origin", {
                "swap_sequence": expected_sequence,
                "position": left + 1,
                "switch_button_index": left,
                "selector": swap["selector"],
                "expected_controls_before": 15,
            }),
            DriverStep(start + len(steps) + 1, "select_swap_target", {
                "swap_sequence": expected_sequence,
                "position": right + 1,
                "switch_button_index": right,
                "selector": swap["selector"],
                "expected_controls_before": 15,
            }),
        ])
        simulated[left], simulated[right] = simulated[right], simulated[left]
    if simulated != target:
        raise DriverPlanBlocked(
            "LINEUP_SWAP_REPLAY_MISMATCH", "los swaps no reproducen el orden target",
        )
    steps.append(DriverStep(start + len(steps), "verify_lineup_visual_order", {
        "player_selector": 'button[data-pitch-element="true"]',
        "expected_slots": labels,
    }))
    return steps


def compile_r2_driver_plan(ui_plan: dict, *, lineup_rehearsed: bool = False) -> dict:
    """Compile the promoted R2 subset into host instructions.

    The compiler rejects any uncertainty before the host claims that the plan
    is executable. Lineup support can be compiled for contract testing, but the
    production caller cannot enable it until a separate rehearsal promotes it.
    """
    if ui_plan.get("schema") != UI_ACTION_PLAN_SCHEMA:
        raise DriverPlanBlocked("UI_PLAN_SCHEMA_INVALID", "UI action plan incompatible")
    if ui_plan.get("status") != "ready" or ui_plan.get("blocking_codes"):
        raise DriverPlanBlocked("UI_PLAN_NOT_READY", "UI action plan no está ready")
    if not str(ui_plan.get("execution_id") or "").startswith("execution_"):
        raise DriverPlanBlocked("EXECUTION_ID_INVALID", "execution_id ausente o inválido")
    if ui_plan.get("swaps") and not lineup_rehearsed:
        raise DriverPlanBlocked(
            "LINEUP_DRIVER_UNPROVEN",
            "los swaps de XI/banca requieren rehearsal vivo antes de promoción",
        )

    commit = ui_plan.get("commit") or {}
    if (
        commit.get("enabled") is not True
        or commit.get("selector") != "button"
        or commit.get("max_clicks") != 1
        or not str(commit.get("accessible_name") or "").strip()
    ):
        raise DriverPlanBlocked(
            "COMMIT_CONTROL_INVALID",
            "el commit único no cumple el contrato",
        )

    steps: list[DriverStep] = _lineup_steps(ui_plan, start=1)
    for role, section_name in (("captain", "captain"), ("vice", "vice_captain")):
        section = ui_plan.get(section_name) or {}
        role_steps = _semantic_steps(section, role=role, start=len(steps) + 1)
        steps.extend(role_steps)
    if not steps:
        raise DriverPlanBlocked("NO_UI_MUTATIONS", "el plan no contiene cambios R2 materiales")

    steps.extend([
        DriverStep(len(steps) + 1, "discover_commit_control", {
            "selector": "button", "accessible_name": commit["accessible_name"],
            "expected_matches": 1,
        }),
        DriverStep(len(steps) + 2, "commit_once", {
            "selector": "button", "accessible_name": commit["accessible_name"],
            "max_clicks": 1,
        }),
        DriverStep(len(steps) + 3, "wait_commit_settled", {
            "accessible_name": commit["accessible_name"],
        }),
        DriverStep(len(steps) + 4, "reload_pick_team", {}),
    ])
    return {
        "schema": DRIVER_PLAN_SCHEMA,
        "contract_version": DRIVER_CONTRACT_VERSION,
        "execution_id": ui_plan["execution_id"],
        "plan_id": ui_plan.get("plan_id"),
        "pre_state_fingerprint": ui_plan.get("pre_state_fingerprint"),
        "scope": "lineup_and_captaincy" if ui_plan.get("swaps") else "captaincy_only",
        "steps": [step.as_dict() for step in steps],
        "failure_policy": {
            "before_begin": "failed",
            "after_begin": "ambiguous",
            "retry_after_commit": False,
        },
    }


def compile_r3_driver_plan(ui_plan: dict) -> dict:
    """Compila R3 a instrucciones tipadas, exclusivamente para validación/rehearsal.

    No existe entrypoint de ejecución: esta función demuestra completitud y
    tamper resistance del contrato sin conceder autoridad browser.
    """
    if ui_plan.get("schema") != R3_UI_ACTION_PLAN_SCHEMA:
        raise DriverPlanBlocked("R3_UI_PLAN_SCHEMA_INVALID", "UI action plan R3 incompatible")
    if ui_plan.get("status") != "ready" or ui_plan.get("blocking_codes"):
        raise DriverPlanBlocked("R3_UI_PLAN_NOT_READY", "UI action plan R3 no está ready")
    if not str(ui_plan.get("execution_id") or "").startswith("execution_"):
        raise DriverPlanBlocked("EXECUTION_ID_INVALID", "execution_id ausente o inválido")
    transfers = list(ui_plan.get("transfers") or ())
    chip = ui_plan.get("chip")
    if not transfers and not chip:
        raise DriverPlanBlocked("NO_R3_MUTATIONS", "el plan no contiene cambios R3")

    economics = ui_plan.get("economics") or {}
    preview = ui_plan.get("preview") or {}
    if (
        preview.get("required") is not True
        or int(preview.get("exact_transfer_count", -1)) != len(transfers)
        or int(preview.get("expected_hits", -1)) != int(economics.get("expected_hits", -2))
        or int(preview.get("expected_bank_after", -1)) != int(economics.get("bank_after", -2))
        or int(economics.get("bank_after", -1)) < 0
    ):
        raise DriverPlanBlocked("R3_PREVIEW_CONTRACT_INVALID", "preview/economía R3 inconsistente")

    steps: list[DriverStep] = [
        DriverStep(1, "open_transfers", {"path": "/en/transfers"}),
        DriverStep(2, "verify_pre_state_bound", {
            "pre_state_fingerprint": ui_plan.get("pre_state_fingerprint"),
            "expected_squad_size": 15,
        }),
    ]
    seen_out: set[int] = set()
    seen_in: set[int] = set()
    for sequence, row in enumerate(transfers, start=1):
        outgoing = row.get("out") or {}
        incoming = row.get("in") or {}
        out_element, in_element = int(outgoing.get("element", 0)), int(incoming.get("element", 0))
        if (
            row.get("operation") != "replace_player"
            or int(row.get("sequence", 0)) != sequence
            or out_element <= 0 or in_element <= 0
            or out_element in seen_out or in_element in seen_in
            or outgoing.get("selector") != 'button[aria-label="Remove player"]'
            or incoming.get("selector") != 'button[aria-label="Add player"]'
            or incoming.get("searchbox_name") != "Find a player"
            or not str(outgoing.get("web_name") or "").strip()
            or not str(incoming.get("web_name") or "").strip()
            or not 1 <= int(outgoing.get("position", 0)) <= 15
            or not 1 <= int(incoming.get("element_type", 0)) <= 4
        ):
            raise DriverPlanBlocked(
                "R3_TRANSFER_ACTION_INVALID", f"transfer {sequence} no cumple el contrato",
            )
        seen_out.add(out_element)
        seen_in.add(in_element)
        steps.extend([
            DriverStep(len(steps) + 1, "remove_exact_player", {
                "element": out_element, "position": int(outgoing["position"]),
                "web_name": outgoing["web_name"], "expected_matches": 1,
            }),
            DriverStep(len(steps) + 1, "search_exact_player", {
                "element": in_element, "web_name": incoming["web_name"],
                "team": incoming.get("team"), "element_type": int(incoming["element_type"]),
                "price": int(incoming["price"]), "searchbox_name": "Find a player",
            }),
            DriverStep(len(steps) + 1, "add_exact_player", {
                "element": in_element, "web_name": incoming["web_name"],
                "expected_matches": 1,
            }),
        ])
    if chip:
        if (
            chip.get("operation") != "stage_chip"
            or chip.get("route") not in {"transfers", "pick_team"}
            or chip.get("selector") != "button"
            or int(chip.get("max_clicks", 0)) != 1
            or not str(chip.get("accessible_name") or "").strip()
        ):
            raise DriverPlanBlocked("R3_CHIP_ACTION_INVALID", "acción de chip inválida")
        steps.append(DriverStep(len(steps) + 1, "stage_chip_once", {
            "chip": chip["chip"], "route": chip["route"],
            "accessible_name": chip["accessible_name"], "max_clicks": 1,
        }))
    steps.append(DriverStep(len(steps) + 1, "verify_exact_transfer_preview", {
        "exact_transfer_count": len(transfers),
        "expected_hits": int(preview["expected_hits"]),
        "expected_bank_after": int(preview["expected_bank_after"]),
        "expected_chip": preview.get("expected_chip"),
    }))

    commit = ui_plan.get("commit") or {}
    if (
        commit.get("enabled") is not True or commit.get("selector") != "button"
        or commit.get("accessible_name") != "Make Transfers"
        or commit.get("confirmation_required") is not True
        or int(commit.get("max_stage_clicks", 0)) != 1
        or int(commit.get("max_confirmation_clicks", 0)) != 1
    ):
        raise DriverPlanBlocked("R3_COMMIT_CONTROL_INVALID", "commit R3 no cumple apply-once")
    steps.extend([
        DriverStep(len(steps) + 1, "open_transfer_review_once", {
            "accessible_name": "Make Transfers", "max_clicks": 1,
        }),
        DriverStep(len(steps) + 1, "verify_review_dialog_exact", {
            "expected_transfer_count": len(transfers),
            "expected_hits": int(preview["expected_hits"]),
            "expected_chip": preview.get("expected_chip"),
        }),
        DriverStep(len(steps) + 1, "confirm_irreversible_once", {
            "semantic_role": "dialog_primary_action", "max_clicks": 1,
            "requires_live_rehearsal": True,
        }),
        DriverStep(len(steps) + 1, "reload_and_read_private_post_state", {}),
    ])
    policy = ui_plan.get("failure_policy") or {}
    if (
        policy.get("retry_after_commit") is not False
        or int(policy.get("max_irreversible_confirmations", 0)) != 1
    ):
        raise DriverPlanBlocked("R3_FAILURE_POLICY_INVALID", "policy apply-once R3 inválida")
    return {
        "schema": R3_DRIVER_PLAN_SCHEMA,
        "contract_version": R3_DRIVER_CONTRACT_VERSION,
        "execution_id": ui_plan["execution_id"], "plan_id": ui_plan.get("plan_id"),
        "scope": ui_plan.get("scope"),
        "steps": [step.as_dict() for step in steps],
        "failure_policy": {
            "before_first_commit": "failed",
            "at_or_after_first_commit": "ambiguous",
            "retry_after_commit": False,
            "max_irreversible_confirmations": 1,
        },
        "production_entrypoint_enabled": False,
    }
