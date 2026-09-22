from pathlib import Path
import os
import subprocess
import time

import pytest


def test_private_state_host_config_wins_over_container_runtime_paths():
    script = Path("deploy/bin/collect-private-team-state.sh").read_text(encoding="utf-8")
    source_loop = 'for env_file in "$runtime_env" "$deploy_env"; do'
    assert source_loop in script
    assert script.index(source_loop) < script.index("docker compose")
    assert "deploy.env contiene las rutas fuente del host" in script


def test_private_state_capture_remains_read_only_and_ephemeral():
    script = Path("deploy/bin/collect-private-team-state.sh").read_text(encoding="utf-8")
    assert 'browser-session.sh" collect' in script
    assert "mktemp /var/lib/mova-fpl/private-team-state" in script
    assert 'rm -f "$private_input"' in script
    assert "ingest-team-state --file -" in script
    assert not any(token in script for token in (
        "execute begin", "execute finalize", "browser_writes=true", "probe-transfers",
    ))


@pytest.mark.parametrize("marker,reason", [
    (str(int(time.time()) + 1800), "private_state_recovery_cooldown"),
    ("invalid", "private_state_retry_marker_invalid"),
])
def test_recovery_gate_blocks_before_starting_docker(tmp_path, marker, reason):
    retry = tmp_path / "retry"
    retry.write_text(marker + "\n")
    env = dict(os.environ, MOVA_REPO_DIR=str(tmp_path),
               MOVA_DEPLOY_ENV=str(tmp_path / "absent-deploy"),
               MOVA_ENV_FILE=str(tmp_path / "absent-runtime"),
               MOVA_PRIVATE_STATE_LOCK_FILE=str(tmp_path / "private.lock"),
               MOVA_CAPACITY_LOCK_FILE=str(tmp_path / "capacity.lock"),
               MOVA_PRIVATE_RETRY_MARKER=str(retry))
    result = subprocess.run(["bash", "deploy/bin/collect-private-team-state.sh"],
                            env=env, capture_output=True, text=True, timeout=5)
    assert result.returncode == 1
    assert reason in result.stdout + result.stderr
    assert "docker" not in result.stderr


def test_capture_is_bounded_and_success_clears_retry_only_after_ingest():
    script = Path("deploy/bin/collect-private-team-state.sh").read_text()
    assert 'timeout --kill-after=5s 120s' in script
    assert 'for attempt in 1; do' in script
    assert script.index('ingest-team-state --file -') < script.index('rm -f "$retry_marker"')


@pytest.mark.parametrize('lock_kind', ['private', 'capacity'])
def test_busy_host_lock_defers_capture_without_docker(tmp_path, lock_kind):
    import fcntl
    lock = tmp_path / f'{lock_kind}.lock'
    env = dict(os.environ, MOVA_REPO_DIR=str(tmp_path),
               MOVA_DEPLOY_ENV=str(tmp_path / 'absent'), MOVA_ENV_FILE=str(tmp_path / 'absent'),
               MOVA_PRIVATE_STATE_LOCK_FILE=str(tmp_path / 'private.lock'),
               MOVA_CAPACITY_LOCK_FILE=str(tmp_path / 'capacity.lock'),
               MOVA_PRIVATE_RETRY_MARKER=str(tmp_path / 'retry'))
    with lock.open('w') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = subprocess.run(['bash', 'deploy/bin/collect-private-team-state.sh'],
                                env=env, capture_output=True, text=True, timeout=5)
    assert result.returncode == 0
    assert 'lock_busy' in result.stdout
    assert not (tmp_path / 'retry').exists()


def test_failed_auth_preserves_cooldown_across_process_restart(tmp_path):
    fake_bin = tmp_path / 'bin'
    fake_bin.mkdir()
    scripts = tmp_path / 'deploy/bin'
    scripts.mkdir(parents=True)
    calls = tmp_path / 'calls'
    docker = fake_bin / 'docker'
    docker.write_text('#!/bin/sh\necho docker >> "$TEST_CALLS"\nexit 0\n')
    mktemp = fake_bin / 'mktemp'
    mktemp.write_text('#!/bin/sh\nexec /usr/bin/mktemp "$TEST_TMP/input.XXXXXX"\n')
    browser = scripts / 'browser-session.sh'
    browser.write_text('#!/bin/sh\necho browser >> "$TEST_CALLS"\nexit 1\n')
    for script in (docker, mktemp, browser):
        script.chmod(0o755)
    retry = tmp_path / 'retry'
    env = dict(os.environ, PATH=str(fake_bin) + ':' + os.environ['PATH'],
               MOVA_REPO_DIR=str(tmp_path), MOVA_DEPLOY_ENV=str(tmp_path / 'absent'),
               MOVA_ENV_FILE=str(tmp_path / 'absent'), MOVA_BROWSER_KEEP_RUNNING='1',
               MOVA_PRIVATE_STATE_LOCK_FILE=str(tmp_path / 'private.lock'),
               MOVA_CAPACITY_LOCK_FILE=str(tmp_path / 'capacity.lock'),
               MOVA_PRIVATE_RETRY_MARKER=str(retry), TEST_CALLS=str(calls), TEST_TMP=str(tmp_path))
    command = ['bash', 'deploy/bin/collect-private-team-state.sh']
    first = subprocess.run(command, env=env, capture_output=True, text=True, timeout=5)
    assert first.returncode == 1
    assert retry.exists()
    assert not list(tmp_path.glob('input.*'))
    previous_calls = calls.read_text()
    second = subprocess.run(command, env=env, capture_output=True, text=True, timeout=5)
    assert second.returncode == 1
    assert 'private_state_recovery_cooldown' in second.stdout
    assert calls.read_text() == previous_calls
