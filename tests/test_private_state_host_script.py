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
