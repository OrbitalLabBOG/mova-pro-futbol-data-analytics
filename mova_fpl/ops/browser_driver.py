"""Typed host-driver contract for reversible FPL browser actions.

This module is deliberately free of CDP and subprocess primitives.  It turns a
validated UI action plan into a small instruction stream that the host adapter
can execute.  Lineup swaps remain fail-closed until their live interaction has
been rehearsed; captain and vice-captain use the semantic controls already
observed in production.
"""

from __future__ import annotations

from dataclasses import dataclass

from mova_fpl.ops.browser_contract import UI_ACTION_PLAN_SCHEMA


DRIVER_PLAN_SCHEMA = "mova-browser-r2-driver-plan-v1"
DRIVER_CONTRACT_VERSION = "fpl-r2-host-driver-2026.08.1"


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


def compile_r2_driver_plan(ui_plan: dict) -> dict:
    """Compile the promoted captaincy-only R2 subset into host instructions.

    The compiler rejects any uncertainty before the host claims that the plan
    is executable.  In particular, lineup swaps are not silently ignored.
    """
    if ui_plan.get("schema") != UI_ACTION_PLAN_SCHEMA:
        raise DriverPlanBlocked("UI_PLAN_SCHEMA_INVALID", "UI action plan incompatible")
    if ui_plan.get("status") != "ready" or ui_plan.get("blocking_codes"):
        raise DriverPlanBlocked("UI_PLAN_NOT_READY", "UI action plan no está ready")
    if not str(ui_plan.get("execution_id") or "").startswith("execution_"):
        raise DriverPlanBlocked("EXECUTION_ID_INVALID", "execution_id ausente o inválido")
    if ui_plan.get("swaps"):
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

    steps: list[DriverStep] = []
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
        "scope": "captaincy_only",
        "steps": [step.as_dict() for step in steps],
        "failure_policy": {
            "before_begin": "failed",
            "after_begin": "ambiguous",
            "retry_after_commit": False,
        },
    }
