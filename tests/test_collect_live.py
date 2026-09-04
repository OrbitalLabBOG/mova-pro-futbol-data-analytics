import json

import pytest

from mova_fpl.cli.collect_live import load_snapshot, validate
from mova_fpl.data.snapshot import (
    capture_bytes,
    event_context,
    load_element_summaries,
    load_event_history,
)


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


def test_event_context_marks_next_gw_preliminary_while_prior_has_pending_match():
    boot, fixtures = sample()
    for fixture in fixtures:
        fixture.update({"started": True, "finished": False})
    boot["events"] = [
        {"id": 1, "deadline_time": "2026-08-21T17:30:00Z", "is_current": True,
         "finished": False, "data_checked": False},
        {"id": 2, "deadline_time": "2026-08-28T17:30:00Z", "is_next": True,
         "finished": False, "data_checked": False},
    ]
    fixtures.append({"id": 11, "event": 1, "team_h": 1, "team_a": 2,
                     "started": False, "finished": False})
    context = event_context(boot, fixtures, 2)
    assert context["current_gw"] == 1
    assert context["prior_settled"] is False
    assert context["prior_unstarted_fixtures"] == 1
    assert context["preliminary"] is True
    assert context["readiness_reasons"] == [
        "prior_gameweek_unsettled", "prior_gameweek_has_unstarted_fixtures"
    ]


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


def test_snapshot_sella_y_verifica_eventos_asentados(tmp_path):
    boot, fixtures = sample()
    boot["events"] = [
        {"id": 1, "deadline_time": "2026-08-21T17:30:00Z",
         "finished": True, "data_checked": True},
        {"id": 2, "deadline_time": "2026-08-28T17:30:00Z",
         "finished": False, "data_checked": False},
    ]
    fixtures.extend([
        {"id": 100 + i, "event": 2, "team_h": i, "team_a": i + 10,
         "kickoff_time": "2026-08-29T14:00:00Z"}
        for i in range(1, 11)
    ])
    boot_raw = json.dumps(boot).encode()
    fixtures_raw = json.dumps(fixtures).encode()
    event_raw = json.dumps({"elements": []}).encode()

    path, manifest = capture_bytes(
        "2026-27", 2, tmp_path, boot_raw, fixtures_raw,
        event_raw={1: event_raw}, captured_at="2026-08-28T10:00:00Z",
    )
    payloads = load_event_history(path, boot, 2)

    assert payloads == {1: {"elements": []}}
    assert manifest["event_live"]["1"]["sha256"]

    (path / "event-live-gw01.json").write_text("{}")
    with pytest.raises(ValueError, match="alterado o corrupto"):
        load_event_history(path, boot, 2)


def test_snapshot_sella_historial_individual_para_cambio_de_club(tmp_path):
    boot, fixtures = sample()
    boot["events"] = [
        {"id": 1, "deadline_time": "2026-08-21T17:30:00Z",
         "finished": True, "data_checked": True},
        {"id": 2, "deadline_time": "2026-08-28T17:30:00Z",
         "finished": False, "data_checked": False},
    ]
    fixtures.extend([
        {"id": 100 + i, "event": 2, "team_h": i, "team_a": i + 10,
         "kickoff_time": "2026-08-29T14:00:00Z"}
        for i in range(1, 11)
    ])
    # Element 1 figura hoy en T1, pero su explicación histórica apunta al
    # fixture 2 (T2-T12): requiere element-summary para identificar el lado.
    event = {"elements": [{
        "id": 1, "stats": {"minutes": 90},
        "explain": [{"fixture": 2, "stats": []}],
    }]}
    summary = {"history": [{
        "round": 1, "fixture": 2, "was_home": True,
    }]}
    path, manifest = capture_bytes(
        "2026-27", 2, tmp_path, json.dumps(boot).encode(),
        json.dumps(fixtures).encode(), event_raw={1: json.dumps(event).encode()},
        element_summary_raw={1: json.dumps(summary).encode()},
        captured_at="2026-08-28T10:00:00Z",
    )
    events = load_event_history(path, boot, 2)
    summaries = load_element_summaries(path, boot, fixtures, events)

    assert summaries == {1: summary}
    assert manifest["element_summary"]["1"]["sha256"]

    (path / "element-summary-1.json").write_text("{}")
    with pytest.raises(ValueError, match="alterado o corrupto"):
        load_element_summaries(path, boot, fixtures, events)
