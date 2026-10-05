"""Regression contracts for the authenticated browser collector."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_private_state_collection_reuses_fpl_origin_without_dom_or_navigation_gate():
    script = (ROOT / "deploy/bin/browser-session.sh").read_text(encoding="utf-8")
    collect_block = script.split("  collect)", maxsplit=1)[1].split(
        "  probe)", maxsplit=1
    )[0]

    assert "open https://fantasy.premierleague.com/en/my-team" not in collect_block
    assert "open https://fantasy.premierleague.com/ >/dev/null" not in collect_block
    assert "location.origin === 'https://fantasy.premierleague.com'" in collect_block
    assert "Switch player" not in collect_block
    assert "private-team-state.js" in collect_block


def test_transfer_probe_waits_for_named_remove_player_controls():
    script = (ROOT / "deploy/bin/browser-session.sh").read_text(encoding="utf-8")
    transfer_block = script.split("  probe-transfers)", maxsplit=1)[1].split(
        "  status)", maxsplit=1
    )[0]

    assert 'button[aria-label^=\\"Remove player\\"]' in transfer_block
    assert 'button[aria-label=\\"Remove player\\"]' not in transfer_block


def test_browser_revision_does_not_invalidate_heavy_dependency_layer():
    dockerfile = (ROOT / "deploy/docker/browser.Dockerfile").read_text(encoding="utf-8")
    dependency_layer = dockerfile.index("RUN apt-get update")
    revision_arg = dockerfile.index("ARG MOVA_GIT_SHA=unknown")

    assert dependency_layer < revision_arg


def test_auth_redirect_is_not_a_pitch_timeout_or_permission_to_submit_credentials():
    script = (ROOT / "deploy/bin/browser-session.sh").read_text()
    collect = script.split("  collect)")[1].split("  probe)")[0]
    assert "FPL_AUTH_INTERACTION_REQUIRED" in collect
    assert "https://accounts.google.com" in collect
    assert "exit 78" in collect
    assert "fill " not in collect
    assert "click " not in collect


def test_collection_waits_for_startup_redirect_before_auth_check_or_private_get():
    script = (ROOT / "deploy/bin/browser-session.sh").read_text()
    collect = script.split("  collect)")[1].split("  probe)")[0]
    stable_route = "location.pathname.startsWith('/en/')"
    document_ready = "['interactive', 'complete'].includes(document.readyState)"
    assert stable_route in collect
    assert document_ready in collect
    assert collect.index(stable_route) < collect.index("auth_pending=")
    assert collect.index(document_ready) < collect.index("private-team-state.js")
    assert "document.querySelector" not in collect
    assert "for attempt" not in collect
    assert "wait --load networkidle" not in collect


def test_borrowed_cpu_requires_both_owned_locks_and_restores_on_probe_failure(tmp_path):
    import os
    import subprocess

    binary=tmp_path/'bin';binary.mkdir()
    log=tmp_path/'docker.log'
    docker=binary/'docker'
    docker.write_text('''#!/usr/bin/env bash
printf '%s\\n' "$*" >>"$TEST_DOCKER_LOG"
if [[ $1 == inspect ]]; then echo 250000000; fi
''')
    curl=binary/'curl';curl.write_text('#!/usr/bin/env bash\nexit 0\n')
    docker.chmod(0o755);curl.chmod(0o755)
    repo=tmp_path/'repo';helper=repo/'deploy/bin/browser-pick-team-probe.py';helper.parent.mkdir(parents=True)
    helper.write_text('import os; print("{}",flush=True); raise SystemExit(int(os.environ["TEST_PROBE_EXIT"]))\n')
    private=tmp_path/'private.lock';capacity=tmp_path/'capacity.lock'
    script=ROOT/'deploy/bin/browser-session.sh'
    env={**os.environ,'PATH':f'{binary}:{os.environ["PATH"]}','TEST_DOCKER_LOG':str(log),
         'MOVA_REPO_DIR':str(repo),'MOVA_DEPLOY_ENV':'/dev/null','TEST_PROBE_EXIT':'7',
         'MOVA_PRIVATE_STATE_LOCK_FILE':str(private),'MOVA_CAPACITY_LOCK_FILE':str(capacity)}
    # Unowned direct read retains the provisioned cap.
    direct=subprocess.run(['bash',str(script),'probe'],env=env,text=True,capture_output=True)
    assert direct.returncode==7
    assert 'update' not in log.read_text()
    log.write_text('')
    # Resource descriptors inherited from the host orchestrator own the same flock.
    driver='exec 9>"$MOVA_PRIVATE_STATE_LOCK_FILE"; flock -n 9; exec 8>"$MOVA_CAPACITY_LOCK_FILE"; flock -n 8; exec bash "$1" probe'
    owned=subprocess.run(['bash','-c',driver,'fixture',str(script)],env=env,text=True,capture_output=True)
    assert owned.returncode==7
    updates=[line for line in log.read_text().splitlines() if line.startswith('update')]
    assert updates==['update --cpus 0.50 mova-fpl-browser-1','update --cpus 0.250000000 mova-fpl-browser-1']
