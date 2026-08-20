import json

import pytest

from mova_fpl.cli.collect_live import load_snapshot, validate


def sample():
    boot = {
        "events": [{"id": 1, "deadline_time": "2026-08-21T17:30:00Z"}],
        "teams": [{"id": i, "name": f"T{i}"} for i in range(1, 21)],
        "elements": [],
    }
    fixtures = []
    element = 1
    for i in range(1, 11):
        fixtures.append({"id": i, "event": 1, "team_h": i, "team_a": i + 10,
                         "kickoff_time": "2026-08-22T14:00:00Z"})
    for team in range(1, 21):
        boot["elements"].append({
            "id": element, "element_type": 1 if team == 1 else 3, "team": team,
            "first_name": "Player", "second_name": str(element), "web_name": str(element),
            "now_cost": 50, "status": "a", "news": "", "selected_by_percent": "0",
        })
        element += 1
    return boot, fixtures


def test_validate_live_snapshot_contract():
    boot, fixtures = sample()
    r = validate(boot, fixtures, "2026-27", 1)
    assert r["teams"] == 20
    assert r["players"] == 20
    assert r["fixtures_gw"] == 10
    assert r["availability_eq_0"] == 0


def test_validate_rejects_incomplete_fixture_list():
    boot, fixtures = sample()
    with pytest.raises(ValueError, match="10 partidos"):
        validate(boot, fixtures[:-1], "2026-27", 1)


def test_load_snapshot_verifies_hashes(tmp_path):
    boot, fixtures = sample()
    boot_raw = json.dumps(boot).encode()
    fixtures_raw = json.dumps(fixtures).encode()
    import hashlib
    (tmp_path / "bootstrap-static.json").write_bytes(boot_raw)
    (tmp_path / "fixtures.json").write_bytes(fixtures_raw)
    (tmp_path / "manifest.json").write_text(json.dumps({
        "bootstrap_sha256": hashlib.sha256(boot_raw).hexdigest(),
        "fixtures_sha256": hashlib.sha256(fixtures_raw).hexdigest(),
    }))
    loaded_boot, loaded_fixtures, _ = load_snapshot(tmp_path)
    assert loaded_boot["events"][0]["id"] == 1
    assert len(loaded_fixtures) == 10

    (tmp_path / "fixtures.json").write_text("[]")
    with pytest.raises(ValueError, match="snapshot alterado"):
        load_snapshot(tmp_path)
