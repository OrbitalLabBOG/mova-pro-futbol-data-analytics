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
