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
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mova_fpl.ops.browser_driver import DriverPlanBlocked, compile_r2_driver_plan


def _emit(event: str, **detail: object) -> None:
    print(json.dumps({"event": event, **detail}, ensure_ascii=False), flush=True)


class AgentBrowser:
    def __init__(self, compose: list[str], *, session: str, cdp_port: int,
                 clock: dict):
        times = [datetime.fromisoformat(clock[key].replace("Z", "+00:00"))
                 for key in ("lease_expires_at", "hard_stop_at")]
        if any(value.tzinfo is None for value in times):
            raise ValueError("EXECUTION_CLOCK_TIMEZONE_REQUIRED")
        if clock.get("verification_reserve_seconds") != 30:
            raise ValueError("EXECUTION_CLOCK_RESERVE_INVALID")
        remaining = (min(times) - datetime.now(timezone.utc)).total_seconds() - 30
        if remaining <= 0:
            raise ValueError("EXECUTION_CLOCK_EXPIRED")
        self.expires_at = min(times)
        self.monotonic_stop = time.monotonic() + remaining
        self.prefix = [
            *compose, "exec", "-T", "browser",
        ]
        self.browser_args = ["agent-browser",
            "--session", session, "--cdp", str(cdp_port),
        ]

    def run(self, *args: str, capture: bool = False) -> str:
        remaining = min(self.monotonic_stop - time.monotonic(),
                        (self.expires_at - datetime.now(timezone.utc)).total_seconds() - 30)
        # Kill the actual browser CLI inside its container as well as bounding
        # the Docker client; a client timeout alone leaves exec work running.
        timeout_seconds = min(30, int(remaining) - 4)
        if timeout_seconds <= 0:
            raise RuntimeError("EXECUTION_CLOCK_EXPIRED")
        result = subprocess.run(
            [*self.prefix, "timeout", "--signal=TERM", "--kill-after=3s",
             f"{timeout_seconds}s", *self.browser_args, *args], check=True, text=True,
            timeout=timeout_seconds + 4,
            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
            stderr=subprocess.PIPE if capture else None,
        )
        return result.stdout.strip() if capture else ""


def _open_player_script(index: int, expected_name: str = '') -> str:
    return (
        "(function(){const visible=n=>Boolean(n&&n.getClientRects().length);"
        "const buttons=Array.from(document.querySelectorAll("
        "'button[data-pitch-element=\\\"true\\\"]')).filter(visible);"
        f"const name={json.dumps(expected_name)};"
        "const matches=name?buttons.slice(0,11).filter(b=>(b.innerText||b.textContent||'').includes(name)):[];"
        f"const player=name?(matches.length===1?matches[0]:null):(buttons.length===15?buttons[{index}]:null);"
        "if(!player)return false;player.click();return true;})()"
    )


def _checkbox_script(name: str, *, checked: bool | None = None, focus: bool = False) -> str:
    expected = json.dumps(name)
    suffix = "return Boolean(node);" if checked is None else (
        f"return Boolean(node&&node.checked==={str(checked).lower()});"
    )
    if focus:
        suffix = "if(!node||node.disabled)return false;node.focus();return document.activeElement===node;"
    return (
        "(function(){const visible=n=>Boolean(n&&n.getClientRects().length);"
        "const nodes=Array.from(document.querySelectorAll('input[type=\\\"checkbox\\\"]'))"
        f".filter(n=>visible(n)&&Array.from(n.labels||[]).some(l=>"
        f"(l.innerText||l.textContent||'').trim()==={expected}));"
        f"const node=nodes.length===1?nodes[0]:null;{suffix}}})()"
    )


TEAM_SAVE_NAMES = ("Save My Team", "Save Your Team", "Save Team", "Confirm My Choices")


def _commit_count_script(name: str | list[str]) -> str:
    expected = json.dumps([name] if isinstance(name, str) else name)
    return (
        "(function(){const visible=n=>Boolean(n&&n.getClientRects().length);"
        f"const names={expected};"
        "return Array.from(document.querySelectorAll('button,input[type=submit]')).filter(b=>visible(b)&&!b.disabled&&"
        "(names.includes((b.innerText||b.textContent||b.value||'').trim())||"
        "names.includes((b.getAttribute('aria-label')||'').trim()))).length;})()"
    )


def _close_sheet_script() -> str:
    return (
        "(function(){const visible=n=>Boolean(n&&n.getClientRects().length);"
        "const buttons=Array.from(document.querySelectorAll('button')).filter(visible);"
        "const b=buttons.find(n=>(n.getAttribute('aria-label')||'').trim()==='Dismiss')||"
        "buttons.find(n=>(n.getAttribute('aria-label')||'').trim()==='Close');"
        "if(!b)return false;b.click();return true;})()"
    )


def _switch_control_script(index: int, expected_name: str = '', *, click: bool = True) -> str:
    return (
        "(function(){const visible=n=>Boolean(n&&n.getClientRects().length);"
        "const buttons=Array.from(document.querySelectorAll("
        "'button[data-pitch-element=\"true\"]')).filter(visible);"
        f"const name={json.dumps(expected_name)};"
        "const named=name?buttons.filter(b=>(b.innerText||b.textContent||'').includes(name)):[];"
        f"const player=name?(named.length===1?named[0]:null):(buttons.length===15?buttons[{index}]:null);"
        "if(!player)return false;"
        "const card=player.parentElement;if(!card||card.querySelectorAll('button[data-pitch-element=\"true\"]').length!==1)return false;"
        "const controls=Array.from(card.querySelectorAll('button[aria-label=\"Switch player\"]')).filter(visible);"
        "if(controls.length!==1||controls[0].disabled)return false;"
        + ("controls[0].click();" if click else "") + "return true;})()"
    )


def _lineup_order_script(expected_slots: list[dict]) -> str:
    expected = json.dumps(expected_slots, ensure_ascii=False)
    return (
        "(function(){const visible=n=>Boolean(n&&n.getClientRects().length);"
        "const buttons=Array.from(document.querySelectorAll("
        "'button[data-pitch-element=\"true\"]')).filter(visible);"
        f"const expected={expected};if(buttons.length!==15||expected.length!==15)return false;"
        "const text=n=>(n.innerText||n.textContent||'').trim().split('\\n')[0].trim();"
        "return expected.slice(0,11).every(row=>buttons.slice(0,11).filter(b=>text(b)===row.web_name).length===1)"
        "&&expected.slice(11).every((row,index)=>text(buttons[index+11])===row.web_name);})()"
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
    commit_name = None
    for step in driver_plan["steps"]:
        operation = step["operation"]
        sequence = int(step["sequence"])
        _emit("browser_driver_step_started", sequence=sequence, operation=operation)
        if operation in {"select_swap_origin", "select_swap_target"}:
            index=int(step['switch_button_index'])
            name=str(step.get('expected_web_name') or '')
            browser.run('wait','--fn',_switch_control_script(index,name,click=False))
            if browser.run(
                "eval", _switch_control_script(index,name),
                capture=True,
            ) != "true":
                raise RuntimeError("FPL_SWITCH_CONTROL_MISSING")
        elif operation == "verify_lineup_visual_order":
            browser.run('wait','--fn',_lineup_order_script(list(step['expected_slots'])))
            if browser.run(
                "eval", _lineup_order_script(list(step["expected_slots"])), capture=True,
            ) != "true":
                raise RuntimeError("FPL_LINEUP_VISUAL_ORDER_MISMATCH")
        elif operation == "open_player_sheet":
            if browser.run("eval", _open_player_script(int(step["player_button_index"]),str(step.get('expected_web_name') or '')),
                           capture=True) != "true":
                raise RuntimeError("FPL_PLAYER_CONTROL_MISSING")
            browser.run("wait", "--fn", _checkbox_script(
                "Captain" if step["role"] == "captain" else "Vice Captain"
            ))
        elif operation == "focus_checkbox":
            # Bind focus to the same unique native input that the probe and
            # verifier identify. The accessibility name can include help text.
            if browser.run('eval', _checkbox_script(str(step['accessible_name']), focus=True),
                           capture=True) != 'true':
                raise RuntimeError('FPL_CHECKBOX_FOCUS_UNPROVEN')
        elif operation == "press_space":
            browser.run("press", "Space")
        elif operation == "verify_checkbox":
            browser.run('wait','--fn',_checkbox_script(str(step['accessible_name']),checked=True))
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
            names = list(dict.fromkeys([str(step['accessible_name']), *TEAM_SAVE_NAMES]))
            count_script = _commit_count_script(names)
            browser.run('wait', '--fn', f"{count_script} === 1")
            if browser.run('eval', count_script, capture=True) != '1':
                raise RuntimeError("FPL_COMMIT_CONTROL_UNPROVEN")
            observed = [name for name in names if browser.run(
                'eval', _commit_count_script(name), capture=True) == '1']
            if len(observed) != 1:
                raise RuntimeError("FPL_COMMIT_CONTROL_AMBIGUOUS")
            commit_name = observed[0]
            _emit('browser_commit_control_observed', accessible_name=commit_name)
        elif operation == "commit_once":
            if not commit_name:
                raise RuntimeError("FPL_COMMIT_CONTROL_UNPROVEN")
            browser.run(
                "find", "role", "button", "click", "--name", commit_name, "--exact",
            )
            _emit("browser_commit_sent", sequence=sequence, max_clicks=1)
        elif operation == "wait_commit_settled":
            browser.run("wait", "--fn", f"{_commit_count_script(commit_name)} === 0")
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
            ui_plan, lineup_rehearsed=True if args.validate_lineup_contract_only else None,
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
    try:
        browser = AgentBrowser(
            ["docker", "compose", "--profile", "browser"],
            session=args.session, cdp_port=args.cdp_port,
            clock=driver_plan.get("execution_clock") or {},
        )
        execute(driver_plan, browser)
    except (RuntimeError, subprocess.SubprocessError, OSError, ValueError, KeyError, TypeError) as exc:
        if 'browser' in locals():
            try:
                diagnostic=browser.run('eval',"JSON.stringify({path:location.pathname,pitch_count:document.querySelectorAll('button[data-pitch-element=\"true\"]').length,commit_controls:[...document.querySelectorAll('button,input[type=submit]')].filter(n=>/save|confirm|choice/i.test((n.innerText||n.textContent||n.value||'')+' '+(n.getAttribute('aria-label')||''))).map(n=>({text:(n.innerText||n.textContent||n.value||'').trim().slice(0,100),label:n.getAttribute('aria-label'),visible:!!n.getClientRects().length,disabled:n.disabled})),switch_controls:[...document.querySelectorAll('button[aria-label]')].filter(n=>n.getClientRects().length&&/switch|swap|cancel/i.test(n.getAttribute('aria-label'))).map(n=>({label:n.getAttribute('aria-label'),disabled:n.disabled}))})",capture=True)
                _emit('browser_driver_failure_controls',observed=json.loads(diagnostic))
            except Exception:
                pass
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
