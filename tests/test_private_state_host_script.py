from pathlib import Path


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
