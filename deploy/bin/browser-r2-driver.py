#!/usr/bin/env python3
"""Materialize the promoted R2 browser instruction subset through agent-browser.

The claim token never reaches this process.  The enclosing host orchestrator
marks the attempt as applying before invoking it and classifies every non-zero
exit after that boundary as ambiguous.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mova_fpl.ops.browser_driver import DriverPlanBlocked, compile_r2_driver_plan


def _emit(event: str, **detail: object) -> None:
    print(json.dumps({"event": event, **detail}, ensure_ascii=False), flush=True)


class AgentBrowser:
    def __init__(self, compose: list[str], *, session: str, cdp_port: int):
        self.prefix = [
            *compose, "exec", "-T", "browser", "agent-browser",
            "--session", session, "--cdp", str(cdp_port),
        ]

    def run(self, *args: str, capture: bool = False) -> str:
        result = subprocess.run(
            [*self.prefix, *args], check=True, text=True,
            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
            stderr=subprocess.PIPE if capture else None,
        )
        return result.stdout.strip() if capture else ""


def _open_player_script(index: int) -> str:
    return (
        "(function(){const visible=n=>Boolean(n&&n.getClientRects().length);"
        "const buttons=Array.from(document.querySelectorAll("
        "'button[data-pitch-element=\\\"true\\\"]')).filter(visible);"
        f"if(buttons.length!==15||!buttons[{index}])return false;"
        f"buttons[{index}].click();return true;}})()"
    )


def _checkbox_script(name: str, *, checked: bool | None = None) -> str:
    expected = json.dumps(name)
    suffix = "return Boolean(node);" if checked is None else (
        f"return Boolean(node&&node.checked==={str(checked).lower()});"
    )
    return (
        "(function(){const visible=n=>Boolean(n&&n.getClientRects().length);"
        "const node=Array.from(document.querySelectorAll('input[type=\\\"checkbox\\\"]'))"
        f".find(n=>visible(n)&&Array.from(n.labels||[]).some(l=>"
        f"(l.innerText||l.textContent||'').trim()==={expected}));{suffix}}})()"
    )


def _commit_count_script(name: str) -> str:
    expected = json.dumps(name)
    return (
        "(function(){const visible=n=>Boolean(n&&n.getClientRects().length);"
        "return Array.from(document.querySelectorAll('button')).filter(b=>visible(b)&&"
        f"((b.innerText||b.textContent||'').trim()==={expected}||"
        f"(b.getAttribute('aria-label')||'').trim()==={expected})).length;}})()"
    )


def _close_sheet_script() -> str:
    return (
        "(function(){const visible=n=>Boolean(n&&n.getClientRects().length);"
        "const b=Array.from(document.querySelectorAll('button[aria-label=\\\"Close\\\"]'))"
        ".find(visible);if(!b)return false;b.click();return true;})()"
    )


def _switch_control_script(index: int) -> str:
    return (
        "(function(){const visible=n=>Boolean(n&&n.getClientRects().length);"
        "const buttons=Array.from(document.querySelectorAll("
        "'button[aria-label=\"Switch player\"]')).filter(visible);"
        f"if(buttons.length!==15||!buttons[{index}])return false;"
        f"buttons[{index}].click();return true;}})()"
    )


def _lineup_order_script(expected_slots: list[dict]) -> str:
    expected = json.dumps(expected_slots, ensure_ascii=False)
    return (
        "(function(){const visible=n=>Boolean(n&&n.getClientRects().length);"
        "const buttons=Array.from(document.querySelectorAll("
        "'button[data-pitch-element=\"true\"]')).filter(visible);"
        f"const expected={expected};if(buttons.length!==15||expected.length!==15)return false;"
        "return expected.every((row,index)=>{const text=(buttons[index].innerText||"
        "buttons[index].textContent||'').trim();return text.includes(row.web_name);});})()"
    )


def _sheet_closed_script() -> str:
    return (
        "(function(){const visible=n=>Boolean(n&&n.getClientRects().length);"
        "return !Array.from(document.querySelectorAll('input[type=\\\"checkbox\\\"]'))"
        ".some(n=>visible(n)&&Array.from(n.labels||[]).some(l=>"
        "['Captain','Vice Captain'].includes("
        "(l.innerText||l.textContent||'').trim())));})()"
    )


def execute(driver_plan: dict, browser: AgentBrowser) -> None:
    if browser.run("get", "url", capture=True).rstrip("/").endswith("/en/my-team") is False:
        raise RuntimeError("FPL_PICK_TEAM_PAGE_REQUIRED")
    for step in driver_plan["steps"]:
        operation = step["operation"]
        sequence = int(step["sequence"])
        _emit("browser_driver_step_started", sequence=sequence, operation=operation)
        if operation in {"select_swap_origin", "select_swap_target"}:
            if browser.run(
                "eval", _switch_control_script(int(step["switch_button_index"])),
                capture=True,
            ) != "true":
                raise RuntimeError("FPL_SWITCH_CONTROL_MISSING")
        elif operation == "verify_lineup_visual_order":
            if browser.run(
                "eval", _lineup_order_script(list(step["expected_slots"])), capture=True,
            ) != "true":
                raise RuntimeError("FPL_LINEUP_VISUAL_ORDER_MISMATCH")
        elif operation == "open_player_sheet":
            if browser.run("eval", _open_player_script(int(step["player_button_index"])),
                           capture=True) != "true":
                raise RuntimeError("FPL_PLAYER_CONTROL_MISSING")
            browser.run("wait", "--fn", _checkbox_script(
                "Captain" if step["role"] == "captain" else "Vice Captain"
            ))
        elif operation == "focus_checkbox":
            browser.run(
                "find", "role", "checkbox", "focus", "--name",
                str(step["accessible_name"]), "--exact",
            )
        elif operation == "press_space":
            browser.run("press", "Space")
        elif operation == "verify_checkbox":
            if browser.run(
                "eval", _checkbox_script(str(step["accessible_name"]), checked=True),
                capture=True,
            ) != "true":
                raise RuntimeError("FPL_CHECKBOX_STATE_MISMATCH")
        elif operation == "close_player_sheet":
            if browser.run("eval", _close_sheet_script(), capture=True) != "true":
                raise RuntimeError("FPL_PLAYER_SHEET_CLOSE_MISSING")
            browser.run("wait", "--fn", _sheet_closed_script())
        elif operation == "discover_commit_control":
            observed = int(browser.run(
                "eval", _commit_count_script(str(step["accessible_name"])), capture=True,
            ))
            if observed != int(step["expected_matches"]):
                raise RuntimeError("FPL_COMMIT_CONTROL_UNPROVEN")
        elif operation == "commit_once":
            browser.run(
                "find", "role", "button", "click", "--name",
                str(step["accessible_name"]), "--exact",
            )
            _emit("browser_commit_sent", sequence=sequence, max_clicks=1)
        elif operation == "wait_commit_settled":
            browser.run("wait", "--fn", (
                "Array.from(document.querySelectorAll('button')).filter(b=>"
                "b.getClientRects().length>0).every(b=>"
                f"(b.innerText||b.textContent||'').trim()!=={json.dumps(step['accessible_name'])})"
            ))
        elif operation == "reload_pick_team":
            browser.run("reload")
            browser.run("wait", "--fn", (
                "location.pathname === '/en/my-team' && "
                "document.querySelectorAll('button[aria-label=\\\"Switch player\\\"]').length === 15"
            ))
        else:  # pragma: no cover - compiler owns the finite instruction set
            raise RuntimeError(f"UNKNOWN_DRIVER_OPERATION:{operation}")
        _emit("browser_driver_step_completed", sequence=sequence, operation=operation)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ui-plan", required=True)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument(
        "--validate-lineup-contract-only", action="store_true",
        help="compila swaps para tests/rehearsal sin iniciar browser ni promover producción",
    )
    parser.add_argument("--session", default="mova-fpl")
    parser.add_argument("--cdp-port", type=int, default=9222)
    args = parser.parse_args()
    try:
        ui_plan = json.loads(Path(args.ui_plan).read_text(encoding="utf-8"))
        driver_plan = compile_r2_driver_plan(
            ui_plan, lineup_rehearsed=args.validate_lineup_contract_only,
        )
    except (OSError, ValueError, TypeError, KeyError, DriverPlanBlocked) as exc:
        _emit(
            "browser_driver_blocked",
            error_code=getattr(exc, "code", type(exc).__name__),
            error_detail=str(exc)[:500],
        )
        return 2
    if args.validate_only or args.validate_lineup_contract_only:
        print(json.dumps(driver_plan, ensure_ascii=False, sort_keys=True))
        return 0
    browser = AgentBrowser(
        ["docker", "compose", "--profile", "browser"],
        session=args.session,
        cdp_port=args.cdp_port,
    )
    try:
        execute(driver_plan, browser)
    except (RuntimeError, subprocess.CalledProcessError, ValueError) as exc:
        _emit(
            "browser_driver_failed", error_code=type(exc).__name__,
            error_detail=str(exc)[:500],
        )
        return 1
    _emit(
        "browser_driver_completed", execution_id=driver_plan["execution_id"],
        steps=len(driver_plan["steps"]), scope=driver_plan["scope"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
