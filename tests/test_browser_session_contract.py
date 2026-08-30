"""Regression contracts for the authenticated browser collector."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_private_state_collection_opens_pick_team_route_directly():
    script = (ROOT / "deploy/bin/browser-session.sh").read_text(encoding="utf-8")
    collect_block = script.split("  collect)", maxsplit=1)[1].split(
        "  probe)", maxsplit=1
    )[0]

    assert "open https://fantasy.premierleague.com/en/my-team" in collect_block
    assert "open https://fantasy.premierleague.com/ >/dev/null" not in collect_block
    assert "location.pathname === '/en/my-team'" in collect_block
    assert "Switch player" in collect_block
