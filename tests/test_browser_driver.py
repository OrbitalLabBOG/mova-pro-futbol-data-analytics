"""HV1-07D.3: promoted host-driver contract remains narrow and fail-closed."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from mova_fpl.ops.browser_driver import DriverPlanBlocked, compile_r2_driver_plan


ROOT = Path(__file__).resolve().parents[1]


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


def test_driver_rejects_lineup_swaps_until_live_rehearsal():
    with pytest.raises(DriverPlanBlocked) as caught:
        compile_r2_driver_plan(_ui_plan(swaps=[{"operation": "switch_slots"}]))
    assert caught.value.code == "LINEUP_DRIVER_UNPROVEN"


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
    assert "printf '%s' \"$claim_token\" | \"$mova_bin\" execute" in script
    assert "rm -f \"$pre_state\" \"$dom_probe\" \"$ui_plan\" \"$post_state\"" in script
    assert "cookies" not in script and "storage" not in script and "state save" not in script


def test_host_orchestrator_runs_claim_apply_verify_once_and_cleans_temp(tmp_path: Path):
    log = tmp_path / "calls.log"
    fake_mova = tmp_path / "mova"
    fake_browser = tmp_path / "browser-session.sh"
    fake_driver = tmp_path / "driver.py"
    fake_mova.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf 'mova %s\\n' "$*" >>"$TEST_CALL_LOG"
case "$1 $2" in
  'execute claim') printf '%s\\n' '{"status":"claimed","claim_token":"secret-once"}' ;;
  'execute ui-plan') printf '%s\\n' '{"status":"ready"}' ;;
  'execute begin') [[ $(cat) == secret-once ]]; printf '%s\\n' '{"status":"applying"}' ;;
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
    }
    subprocess.run(
        ["bash", "deploy/bin/execute-r2-browser.sh",
         "--execution-id", "execution_fixture", "--actor", "test",
         "--reason", "contract rehearsal"],
        cwd=ROOT, env=env, text=True, capture_output=True, check=True,
    )
    calls = log.read_text(encoding="utf-8")
    assert calls.count("execute claim") == 1
    assert calls.count("execute begin") == 1
    assert calls.count("execute finalize") == 1
    assert calls.count("browser collect") == 2
    assert calls.count("browser probe") == 1
    assert calls.count("browser stop") == 1
    assert calls.count("driver ") == 2
    assert "secret-once" not in calls
    assert not list(tmp_path.glob("mova-fpl-r2.*"))
