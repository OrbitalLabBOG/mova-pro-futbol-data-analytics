"""HV1-07D.3: promoted host-driver contract remains narrow and fail-closed."""

from __future__ import annotations

import json
import importlib.util
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mova_fpl.ops.browser_driver import (
    DriverPlanBlocked,
    compile_r2_driver_plan,
    compile_r3_driver_plan,
    driver_capabilities,
)


ROOT = Path(__file__).resolve().parents[1]


def _host_driver_module():
    path = ROOT / "deploy/bin/browser-r2-driver.py"
    spec = importlib.util.spec_from_file_location("mova_browser_r2_driver_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _action(name: str, index: int) -> dict:
    return {
        "operation": "set_player_checkbox",
        "target_position": index + 1,
        "player_button_index": index,
        "player_selector": 'button[data-pitch-element="true"]',
        "checkbox_role": "checkbox",
        "checkbox_accessible_name": name,
        "expected_checked_after": True,
    }


def _ui_plan(*, swaps: list[dict] | None = None) -> dict:
    return {
        "schema": "mova-browser-ui-action-plan-v1",
        "execution_id": "execution_fixture",
        "plan_id": "execplan_fixture",
        "pre_state_fingerprint": "f" * 64,
        "status": "ready",
        "blocking_codes": [],
        "swaps": swaps or [],
        "captain": {"from": 1, "to": 7, "action": _action("Captain", 6)},
        "vice_captain": {
            "from": 2, "to": 8, "action": _action("Vice Captain", 7),
        },
        "commit": {
            "selector": "button", "accessible_name": "Confirm My Choices",
            "max_clicks": 1, "enabled": True,
        },
    }


def _lineup_ui_plan() -> dict:
    payload = _ui_plan(swaps=[
        {
            "sequence": 1, "operation": "switch_slots",
            "first_position": 11, "second_position": 12,
            "first_index": 10, "second_index": 11,
            "selector": 'button[aria-label="Switch player"]',
        },
    ])
    payload["captain"]["action"] = None
    payload["vice_captain"]["action"] = None
    payload["lineup"] = {
        "from_order": list(range(1, 16)),
        "to_order": list(range(1, 11)) + [12, 11, 13, 14, 15],
        "swap_count": 1,
        "target_slots": [
            {"position": position, "element": element,
             "web_name": f"Player {element}"}
            for position, element in enumerate(
                list(range(1, 11)) + [12, 11, 13, 14, 15], start=1,
            )
        ],
    }
    return payload


def test_captaincy_driver_plan_is_ordered_and_apply_once():
    plan = compile_r2_driver_plan(_ui_plan())
    operations = [row["operation"] for row in plan["steps"]]
    assert plan["scope"] == "captaincy_only"
    assert operations[:5] == [
        "open_player_sheet", "focus_checkbox", "press_space",
        "verify_checkbox", "close_player_sheet",
    ]
    assert operations[5:10] == operations[:5]
    assert operations[-4:] == [
        "discover_commit_control", "commit_once", "wait_commit_settled",
        "reload_pick_team",
    ]
    commits = [row for row in plan["steps"] if row["operation"] == "commit_once"]
    assert len(commits) == 1 and commits[0]["max_clicks"] == 1
    assert plan["failure_policy"]["retry_after_commit"] is False


def test_driver_capability_ledger_keeps_lineup_and_r3_unpromoted():
    capabilities = driver_capabilities()
    assert capabilities["captaincy"]["host_entrypoint_enabled"] is True
    assert capabilities["captaincy"]["autonomy_promoted"] is False
    assert capabilities["lineup"] == {
        "contract": "implemented", "host_entrypoint_enabled": False,
        "autonomy_promoted": False, "observed_rehearsals": 0,
        "required_rehearsals": 3,
    }
    assert capabilities["r3"] == {
        "contract": "implemented", "host_entrypoint_enabled": False,
        "autonomy_promoted": False, "observed_rehearsals": 0,
        "required_rehearsals": 3,
    }


def _r3_ui_plan() -> dict:
    return {
        "schema": "mova-browser-r3-ui-action-plan-v1",
        "execution_id": "execution_r3_fixture", "plan_id": "execplan_r3_fixture",
        "pre_state_fingerprint": "f" * 64, "status": "ready",
        "blocking_codes": [], "scope": "transfers_and_chip",
        "transfers": [{
            "sequence": 1, "operation": "replace_player",
            "out": {"element": 2, "position": 2, "web_name": "Player 2",
                    "selector": 'button[aria-label^="Remove player"]'},
            "in": {"element": 16, "element_type": 2, "web_name": "Player 16",
                   "team": "Test FC", "price": 45,
                   "searchbox_name": "Find a player",
                   "selector": 'button[aria-label^="Add player"]'},
        }],
        "economics": {"bank_after": 15, "expected_hits": 0},
        "chip": {"operation": "stage_chip", "chip": "wildcard",
                 "route": "transfers", "selector": "button",
                 "accessible_name": "Wildcard Play", "max_clicks": 1},
        "preview": {"required": True, "exact_transfer_count": 1,
                    "expected_hits": 0, "expected_bank_after": 15,
                    "expected_chip": "wildcard"},
        "commit": {"selector": "button", "accessible_name": "Make Transfers",
                   "confirmation_required": True, "max_stage_clicks": 1,
                   "max_confirmation_clicks": 1, "enabled": True},
        "failure_policy": {"retry_after_commit": False,
                           "max_irreversible_confirmations": 1},
    }


def test_r3_driver_contract_compiles_but_has_no_production_entrypoint():
    plan = compile_r3_driver_plan(_r3_ui_plan())
    operations = [row["operation"] for row in plan["steps"]]
    assert plan["production_entrypoint_enabled"] is False
    assert operations[:2] == ["open_transfers", "verify_pre_state_bound"]
    assert operations[-4:] == [
        "open_transfer_review_once", "verify_review_dialog_exact",
        "confirm_irreversible_once", "reload_and_read_private_post_state",
    ]
    assert sum(row["operation"] == "confirm_irreversible_once"
               for row in plan["steps"]) == 1
    assert plan["failure_policy"]["retry_after_commit"] is False


def test_r3_host_tool_is_validation_only(tmp_path: Path):
    path = tmp_path / "r3-ui-plan.json"
    path.write_text(json.dumps(_r3_ui_plan()), encoding="utf-8")
    result = subprocess.run(
        ["python3", "deploy/bin/browser-r3-driver.py", "--ui-plan", str(path),
         "--validate-contract-only"], cwd=ROOT, text=True, capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)
    assert payload["schema"] == "mova-browser-r3-driver-plan-v1"
    assert payload["production_entrypoint_enabled"] is False
    script = (ROOT / "deploy/bin/browser-r3-driver.py").read_text(encoding="utf-8")
    assert "AgentBrowser" not in script and "subprocess" not in script


@pytest.mark.parametrize("tamper", ["duplicate", "preview", "commit"])
def test_r3_driver_contract_rejects_tampering(tamper):
    payload = _r3_ui_plan()
    if tamper == "duplicate":
        payload["transfers"].append(dict(payload["transfers"][0], sequence=2))
    elif tamper == "preview":
        payload["preview"]["exact_transfer_count"] = 2
    else:
        payload["commit"]["max_confirmation_clicks"] = 2
    with pytest.raises(DriverPlanBlocked) as caught:
        compile_r3_driver_plan(payload)
    assert caught.value.code.startswith("R3_")


def test_driver_rejects_lineup_swaps_until_live_rehearsal():
    with pytest.raises(DriverPlanBlocked) as caught:
        compile_r2_driver_plan(_ui_plan(swaps=[{"operation": "switch_slots"}]))
    assert caught.value.code == "LINEUP_DRIVER_UNPROVEN"


def test_lineup_contract_compiles_typed_swaps_but_only_with_rehearsal_gate():
    plan = compile_r2_driver_plan(_lineup_ui_plan(), lineup_rehearsed=True)
    assert plan["scope"] == "lineup_and_captaincy"
    assert [row["operation"] for row in plan["steps"]] == [
        "select_swap_origin", "select_swap_target", "verify_lineup_visual_order",
        "discover_commit_control", "commit_once", "wait_commit_settled",
        "reload_pick_team",
    ]
    assert plan["steps"][0]["switch_button_index"] == 10
    assert plan["steps"][1]["switch_button_index"] == 11
    assert len(plan["steps"][2]["expected_slots"]) == 15
    assert sum(row["operation"] == "commit_once" for row in plan["steps"]) == 1


@pytest.mark.parametrize("tamper", ["selector", "replay", "label"])
def test_lineup_contract_rejects_tampering(tamper):
    payload = _lineup_ui_plan()
    if tamper == "selector":
        payload["swaps"][0]["selector"] = "button"
    elif tamper == "replay":
        payload["lineup"]["to_order"] = list(range(1, 16))
    else:
        payload["lineup"]["target_slots"][10]["web_name"] = ""
    with pytest.raises(DriverPlanBlocked) as caught:
        compile_r2_driver_plan(payload, lineup_rehearsed=True)
    assert caught.value.code.startswith("LINEUP_")


@pytest.mark.parametrize("change", [
    {"enabled": False}, {"max_clicks": 2}, {"accessible_name": ""},
])
def test_driver_rejects_unproven_commit_contract(change):
    payload = _ui_plan()
    payload["commit"].update(change)
    with pytest.raises(DriverPlanBlocked) as caught:
        compile_r2_driver_plan(payload)
    assert caught.value.code == "COMMIT_CONTROL_INVALID"


def test_driver_rejects_empty_or_blocked_plan():
    empty = _ui_plan()
    empty["captain"]["action"] = None
    empty["vice_captain"]["action"] = None
    with pytest.raises(DriverPlanBlocked) as caught:
        compile_r2_driver_plan(empty)
    assert caught.value.code == "NO_UI_MUTATIONS"
    blocked = _ui_plan()
    blocked["status"] = "blocked"
    blocked["blocking_codes"] = ["CAPTAIN_CONTROL_UNPROVEN"]
    with pytest.raises(DriverPlanBlocked) as caught:
        compile_r2_driver_plan(blocked)
    assert caught.value.code == "UI_PLAN_NOT_READY"


def test_host_driver_validate_only_never_starts_browser(tmp_path: Path):
    path = tmp_path / "ui-plan.json"
    path.write_text(json.dumps(_ui_plan()), encoding="utf-8")
    result = subprocess.run(
        ["python3", "deploy/bin/browser-r2-driver.py", "--ui-plan", str(path),
         "--validate-only"],
        cwd=ROOT, text=True, capture_output=True, check=True,
    )
    payload = json.loads(result.stdout)
    assert payload["schema"] == "mova-browser-r2-driver-plan-v1"
    assert payload["execution_id"] == "execution_fixture"


def test_host_driver_lineup_contract_mode_never_starts_browser(tmp_path: Path):
    path = tmp_path / "ui-plan.json"
    path.write_text(json.dumps(_lineup_ui_plan()), encoding="utf-8")
    blocked = subprocess.run(
        ["python3", "deploy/bin/browser-r2-driver.py", "--ui-plan", str(path),
         "--validate-only"], cwd=ROOT, text=True, capture_output=True,
    )
    assert blocked.returncode == 2
    assert "LINEUP_DRIVER_UNPROVEN" in blocked.stdout
    validated = subprocess.run(
        ["python3", "deploy/bin/browser-r2-driver.py", "--ui-plan", str(path),
         "--validate-lineup-contract-only"], cwd=ROOT, text=True,
        capture_output=True, check=True,
    )
    payload = json.loads(validated.stdout)
    assert payload["scope"] == "lineup_and_captaincy"
    assert payload["contract_version"] == "fpl-r2-host-driver-2026.10.1"


def test_host_driver_prefers_current_dismiss_control_for_player_sheet():
    script = _host_driver_module()._close_sheet_script()

    assert "Dismiss" in script
    assert script.index("Dismiss") < script.index("Close")


def test_host_driver_enforces_clock_and_bounds_container_command(monkeypatch):
    module = _host_driver_module()
    now = datetime.now(timezone.utc)
    clock = {"lease_expires_at": (now + timedelta(minutes=5)).isoformat(),
             "hard_stop_at": (now + timedelta(minutes=10)).isoformat(),
             "verification_reserve_seconds": 30}
    calls = []
    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="true")
    monkeypatch.setattr(module.subprocess, "run", fake_run)
    browser = module.AgentBrowser(["docker", "compose"], session="fixture", cdp_port=9222, clock=clock)
    assert browser.run("eval", "true", capture=True) == "true"
    argv, options = calls[0]
    assert argv[:6] == ["docker", "compose", "exec", "-T", "browser", "timeout"]
    assert "--kill-after=3s" in argv
    assert 0 < options["timeout"] <= 34
    browser.monotonic_stop = 0
    with pytest.raises(RuntimeError, match="EXECUTION_CLOCK_EXPIRED"):
        browser.run("find", "role", "button", "click", "--name", "Save")
    assert len(calls) == 1


def test_lineup_instruction_stream_materializes_against_fake_browser():
    module = _host_driver_module()
    plan = compile_r2_driver_plan(_lineup_ui_plan(), lineup_rehearsed=True)

    class FakeBrowser:
        def __init__(self):
            self.calls = []

        def run(self, *args, capture=False):
            self.calls.append((args, capture))
            if args[:2] == ("get", "url"):
                return "https://fantasy.premierleague.com/en/my-team"
            if args[0] == "eval" and "querySelectorAll('button')" in args[1]:
                return "1"
            if args[0] == "eval":
                return "true"
            return ""

    browser = FakeBrowser()
    module.execute(plan, browser)
    eval_scripts = [args[1] for args, _ in browser.calls if args[0] == "eval"]
    assert sum('Switch player' in script for script in eval_scripts) == 2
    assert sum('data-pitch-element' in script for script in eval_scripts) == 1
    assert sum(args[0] == "reload" for args, _ in browser.calls) == 1
    assert sum(args[0] == "find" and args[-1] == "--exact"
               for args, _ in browser.calls) == 1


def test_host_orchestrator_keeps_claim_secret_in_pipe_and_cleans_up():
    script = (ROOT / "deploy/bin/execute-r2-browser.sh").read_text(encoding="utf-8")
    subprocess.run(
        ["bash", "-n", "deploy/bin/execute-r2-browser.sh"], cwd=ROOT, check=True,
    )
    assert "umask 077" in script
    assert 'run_root=${MOVA_RUN_ROOT:-/run}' in script
    assert 'mktemp -d "$run_root/mova-fpl-r2.' in script
    assert "--claim-token-stdin" in script
    assert "--claim-token " not in script
    assert "printf '%s' \"$claim_token\" | bounded 30 \"$mova_bin\" execute begin" in script
    assert "rm -f \"$pre_state\" \"$dom_probe\" \"$ui_plan\" \"$post_state\"" in script
    assert "cookies" not in script and "storage" not in script and "state save" not in script


def test_transfer_probe_is_read_only_allowlisted_and_numeric_only():
    session = (ROOT / "deploy/bin/browser-session.sh").read_text(encoding="utf-8")
    probe = (ROOT / "deploy/browser/transfers-dom-probe.js").read_text(encoding="utf-8")
    subprocess.run(["bash", "-n", "deploy/bin/browser-session.sh"], cwd=ROOT, check=True)
    assert "probe-transfers" in session
    assert "comma-separated numeric allowlist" in session
    assert "credentials: \"include\"" in probe
    assert "targetIds" in probe and "targets_complete" in probe
    assert "Search by name" in probe and ".replace(/\\s+/g" in probe
    assert ".click(" not in probe
    assert "localStorage" not in probe and "document.cookie" not in probe


@pytest.mark.parametrize("begin_mode", ["ok", "lost_applying", "lost_claimed"])
def test_host_orchestrator_runs_claim_apply_verify_once_and_cleans_temp(tmp_path: Path, begin_mode):
    log = tmp_path / "calls.log"
    fake_mova = tmp_path / "mova"
    fake_browser = tmp_path / "browser-session.sh"
    fake_driver = tmp_path / "driver.py"
    fake_mova.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf 'mova %s\\n' "$*" >>"$TEST_CALL_LOG"
case "$1 $2" in
  'execute claim') python3 -c 'import json; from datetime import datetime,timedelta,timezone; print(json.dumps({"status":"claimed","claim_token":"secret-once","lease_expires_at":(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()}))' ;;
  'execute ui-plan') printf '%s\\n' '{"status":"ready"}' ;;
  'execute begin') [[ $(cat) == secret-once ]]; [[ $TEST_BEGIN_MODE == ok ]] || exit 9; printf '%s\\n' '{"status":"applying"}' ;;
  'execute fail') [[ $(cat) == secret-once ]]; if [[ $TEST_BEGIN_MODE == lost_claimed && $* == *ambiguous* ]]; then exit 9; fi; printf '%s\\n' '{"status":"failed"}' ;;
  'execute finalize') [[ $(cat) == secret-once ]]; printf '%s\\n' '{"status":"verified"}' ;;
  *) exit 9 ;;
esac
""",
        encoding="utf-8",
    )
    fake_browser.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf 'browser %s\\n' "$1" >>"$TEST_CALL_LOG"
case "$1" in collect|probe) printf '%s\\n' '{}' ;; stop) : ;; *) exit 9 ;; esac
""",
        encoding="utf-8",
    )
    fake_driver.write_text(
        """import os, sys
with open(os.environ['TEST_CALL_LOG'], 'a', encoding='utf-8') as stream:
    stream.write('driver ' + ' '.join(sys.argv[1:]) + '\\n')
""",
        encoding="utf-8",
    )
    fake_mova.chmod(0o755)
    fake_browser.chmod(0o755)
    env = {
        **os.environ,
        "MOVA_REPO_DIR": str(ROOT),
        "MOVA_RUN_ROOT": str(tmp_path),
        "MOVA_BIN": str(fake_mova),
        "MOVA_BROWSER_SESSION_BIN": str(fake_browser),
        "MOVA_BROWSER_R2_DRIVER": str(fake_driver),
        "TEST_CALL_LOG": str(log),
        "TEST_BEGIN_MODE": begin_mode,
    }
    result = subprocess.run(
        ["bash", "deploy/bin/execute-r2-browser.sh",
         "--execution-id", "execution_fixture", "--actor", "test",
         "--reason", "contract rehearsal"],
        cwd=ROOT, env=env, text=True, capture_output=True,
    )
    calls = log.read_text(encoding="utf-8")
    assert calls.count("execute claim") == 1
    assert calls.count("execute begin") == 1
    assert result.returncode == (0 if begin_mode == "ok" else 2)
    assert calls.count("execute finalize") == (1 if begin_mode == "ok" else 0)
    assert calls.count("execute fail") == {"ok": 0, "lost_applying": 1, "lost_claimed": 2}[begin_mode]
    if begin_mode != "ok":
        assert "--classification ambiguous" in calls
    if begin_mode == "lost_claimed":
        assert "--classification failed" in calls
    assert calls.count("browser collect") == (2 if begin_mode == "ok" else 1)
    assert calls.count("browser probe") == 1
    assert calls.count("browser stop") == 1
    assert sum(line.startswith("driver ") for line in calls.splitlines()) == (2 if begin_mode == "ok" else 1)
    assert "secret-once" not in calls
    assert not list(tmp_path.glob("mova-fpl-r2.*"))


@pytest.mark.parametrize('kind,expected', [('correct', True), ('wrong_order', False),
                                          ('missing_player', False), ('hidden_player', False)])
def test_lineup_dom_order_scripts_against_sanitized_nodes(kind, expected):
    import shutil
    node = shutil.which('node')
    if not node: pytest.skip('Node runtime required for DOM-script contract tests')
    module = _host_driver_module()
    slots = [{'position': i, 'element': i, 'web_name': f'Player {i}'} for i in range(1, 16)]
    names = [s['web_name'] for s in slots]
    if kind == 'wrong_order': names[10], names[11] = names[11], names[10]
    if kind == 'missing_player': names.pop()
    harness = """
const fs=require('fs'),vm=require('vm');const p=JSON.parse(fs.readFileSync(0,'utf8'));
const nodes=p.names.map((name,i)=>({innerText:name,getClientRects:()=>p.hidden&&i===14?[]:[{}]}));
const document={querySelectorAll:()=>nodes};
process.stdout.write(JSON.stringify(vm.runInNewContext(p.script,{document}, {timeout:1000})));
"""
    result = subprocess.run([node, '-e', harness], input=json.dumps({
        'names': names, 'hidden': kind == 'hidden_player', 'script': module._lineup_order_script(slots)}),
        text=True, capture_output=True, check=True)
    assert json.loads(result.stdout) is expected


@pytest.mark.parametrize('failure', ['missing_switch', 'wrong_visual_order', 'ambiguous_commit', 'late_response'])
def test_lineup_failures_stop_before_commit(failure):
    module = _host_driver_module()
    plan = compile_r2_driver_plan(_lineup_ui_plan(), lineup_rehearsed=True)
    class Browser:
        def __init__(self): self.commits = 0
        def run(self, *args, capture=False):
            if args[:2] == ('get', 'url'): return 'https://fantasy.premierleague.com/en/my-team'
            if args[0] == 'find' and 'click' in args: self.commits += 1
            if args[0] == 'eval':
                script = args[1]
                if failure == 'missing_switch' and 'Switch player' in script: return 'false'
                if failure == 'wrong_visual_order' and 'const expected=' in script: return 'false'
                if "querySelectorAll('button')" in script: return '2' if failure == 'ambiguous_commit' else '1'
                if failure == 'late_response': raise RuntimeError('DOM_RESPONSE_TIMEOUT')
                return 'true'
            return ''
    browser = Browser()
    with pytest.raises(RuntimeError): module.execute(plan, browser)
    assert browser.commits == 0


def test_timeout_after_commit_does_not_retry_click():
    module = _host_driver_module()
    plan = compile_r2_driver_plan(_lineup_ui_plan(), lineup_rehearsed=True)
    class Browser:
        def __init__(self): self.commits = 0
        def run(self, *args, capture=False):
            if args[:2] == ('get', 'url'): return 'https://fantasy.premierleague.com/en/my-team'
            if args[0] == 'find' and 'click' in args: self.commits += 1
            if args[0] == 'wait' and self.commits: raise RuntimeError('COMMIT_RESPONSE_TIMEOUT')
            if args[0] == 'eval': return '1' if "querySelectorAll('button')" in args[1] else 'true'
            return ''
    browser = Browser()
    with pytest.raises(RuntimeError, match='COMMIT_RESPONSE_TIMEOUT'): module.execute(plan, browser)
    assert browser.commits == 1
