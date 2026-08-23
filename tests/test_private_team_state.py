from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from mova_fpl.data import live
from mova_fpl.data.private_state import load, seal, validate
from mova_fpl.rules import get as get_rules


def payload() -> dict:
    position_types = [1, 1] + [2] * 5 + [3] * 5 + [4] * 3
    return {
        "schema": "mova-fpl-private-team-state-v1",
        "observed_at": "2026-08-22T22:00:00.000Z",
        "team_id": 3609854,
        "event": {"id": 2, "deadline_time": "2026-08-28T17:30:00Z"},
        "picks_last_updated": "2026-08-20T20:20:04.429580Z",
        "picks": [
            {"element": i, "element_type": kind, "position": i,
             "multiplier": 1 if i <= 11 else 0, "is_captain": i == 1,
             "is_vice_captain": i == 2, "purchase_price": 50 + i,
             "selling_price": 50 + i}
            for i, kind in enumerate(position_types, start=1)
        ],
        "transfers": {"bank": 0, "value": 1000, "limit": 1, "made": 0,
                      "cost": 4, "status": "cost"},
        "chips": [
            {"name": name, "number": 1, "status_for_entry": "available",
             "is_pending": False, "start_event": start, "stop_event": 19}
            for name, start in (("bboost", 1), ("3xc", 1),
                                ("wildcard", 2), ("freehit", 2))
        ],
    }


def bootstrap() -> dict:
    teams = [{"id": i, "name": f"Club{i}"} for i in range(1, 6)]
    elements = []
    for pick in payload()["picks"]:
        elements.append({"id": pick["element"], "element_type": pick["element_type"],
                         "team": 1 + pick["element"] % 5,
                         "now_cost": pick["purchase_price"]})
    return {"teams": teams, "elements": elements}


def roster(boot: dict) -> pd.DataFrame:
    teams = {t["id"]: t["name"] for t in boot["teams"]}
    return pd.DataFrame([
        {"element": e["id"], "position": live.POSICIONES[e["element_type"]],
         "team": teams[e["team"]], "value": e["now_cost"]}
        for e in boot["elements"]
    ])


def test_private_payload_is_strict_and_computes_exact_balance():
    normalized, quality = validate(payload(), expected_team_id=3609854)
    assert len(normalized["picks"]) == 15
    assert quality["free_transfers"] == 1
    assert quality["bank_tenths"] == 0
    assert quality["available_chips"] == ["3xc", "bboost", "freehit", "wildcard"]


def test_private_payload_rejects_fields_outside_allowlist():
    unsafe = payload()
    unsafe["cookies"] = [{"name": "sessionid", "value": "secret"}]
    with pytest.raises(ValueError, match="no permitidos"):
        validate(unsafe, expected_team_id=3609854)


def test_private_snapshot_is_immutable_and_hash_checked(tmp_path):
    path, _, _ = seal(payload(), "2026-27", tmp_path, expected_team_id=3609854)
    loaded, _ = load(path, expected_team_id=3609854)
    assert loaded["team_id"] == 3609854
    (path / "team-state.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="alterado"):
        load(path, expected_team_id=3609854)


def test_private_squad_preserves_purchase_prices(monkeypatch):
    boot = bootstrap()
    monkeypatch.setattr(live, "fetch_team_history",
                        lambda _: json.dumps({"chips": [], "current": [], "past": []}).encode())
    state = live.private_team_state(
        payload(), 3609854, 2, roster(boot), get_rules("2026-27").SQUAD, boot,
    )
    assert len(state["squad"].players) == 15
    assert state["squad"].players[0].purchase_price == pytest.approx(5.1)
    assert state["free_transfers"] == 1
    assert state["source"] == "authenticated_api"
