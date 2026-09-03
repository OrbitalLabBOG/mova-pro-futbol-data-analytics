"""Pruebas del cierre local de la primera observación live."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from experiments.long_horizon.live_settlement import (
    build_settlement,
    event_readiness,
    load_frozen_observation,
    manual_from_public_picks,
)
from mova_fpl.engine.state import Decision
from mova_fpl.ops.collector.contracts import canonical_bytes


def _shadow() -> dict:
    squad = tuple(range(1, 16))
    common = dict(
        season="2026-27", gw=4, squad_15=squad,
        starters=(1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15),
        vice_captain=8, bench_order=(2, 6, 7, 12),
        expected_points=50.0, total_cost=75.0, bank_after=25.0, policy="milp",
    )
    control = Decision(captain=8, **common)
    candidate = Decision(captain=9, **common)
    xp = {element: element / 10.0 for element in squad}
    return {
        "schema": "mova-strategy-shadow-v1",
        "experiment_id": "EXP-MOVA-2026-003",
        "strategy_key": "season_fixture_h3",
        "season": "2026-27", "gw": 4,
        "selected_for_execution": False, "virtual_trajectory": True,
        "trajectory": {"mode": "initialized_from_observed"},
        "chips": "disabled_in_both_arms",
        "control": {"decision": control.to_dict(), "violations": []},
        "candidate": {"decision": candidate.to_dict(), "violations": []},
        "projections": {
            "control_horizon_xp": {4: xp},
            "candidate_horizon_xp": {4: {key: value + 0.2 for key, value in xp.items()}},
            "candidate_horizon_sd": {4: {key: 1.5 for key in xp}},
        },
    }


def _players() -> list[dict]:
    positions = [1, 1] + [2] * 5 + [3] * 5 + [4] * 3
    return [
        {"element": element, "element_type": position, "team_id": element,
         "now_cost": 50, "web_name": f"P{element}"}
        for element, position in zip(range(1, 16), positions)
    ]


def _live() -> list[dict]:
    points = {element: 1 for element in range(1, 16)}
    points[8], points[9] = 2, 10
    return [
        {"element": element, "minutes": 90, "total_points": value}
        for element, value in points.items()
    ]


def _observation(tmp_path: Path) -> tuple[dict, dict, dict]:
    shadow = _shadow()
    shadow["season"], shadow["gw"] = "2026-27", 4
    bundle = {"schema": "mova-live-decision-candidates-v1", "season": "2026-27",
              "gw": 4, "strategy_shadow": shadow}
    bundle_raw = json.dumps(bundle).encode()
    report_raw = b"frozen report\n"
    observation = {
        "schema": "mova-long-horizon-live-observation-v1",
        "experiment_id": "EXP-MOVA-TEST",
        "season": "2026-27", "gw": 4,
        "deadline_at": "2026-09-11T17:30:00+00:00",
        "outputs": {
            "candidate_bundle_sha256": hashlib.sha256(bundle_raw).hexdigest(),
            "report_sha256": hashlib.sha256(report_raw).hexdigest(),
        },
    }
    manifest = {
        "schema": "mova-long-horizon-live-manifest-v1",
        "experiment_id": "EXP-MOVA-TEST",
        "target": {"season": "2026-27", "gw": 4,
                   "deadline_at": "2026-09-11T17:30:00+00:00"},
    }
    (tmp_path / "live-observation.json").write_text(json.dumps(observation))
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    (tmp_path / "gw03-shadow.json").write_bytes(bundle_raw)
    (tmp_path / "gw03-shadow.md").write_bytes(report_raw)
    return observation, bundle, shadow


def _bootstrap(*, checked: bool = True) -> dict:
    players = []
    for row in _players():
        players.append({
            "id": row["element"], "web_name": row["web_name"],
            "team": row["team_id"], "element_type": row["element_type"],
            "now_cost": row["now_cost"],
        })
    return {"events": [{"id": 4, "deadline_time": "2026-09-11T17:30:00Z",
                         "finished": checked, "data_checked": checked}],
            "elements": players}


def _event_live() -> dict:
    return {"elements": [{"id": row["element"], "stats": {
        "minutes": row["minutes"], "total_points": row["total_points"],
    }} for row in _live()]}


def test_frozen_observation_rejects_tampered_bundle(tmp_path: Path):
    _observation(tmp_path)
    load_frozen_observation(tmp_path)
    with (tmp_path / "gw03-shadow.json").open("ab") as handle:
        handle.write(b" ")

    with pytest.raises(ValueError, match="hash del bundle"):
        load_frozen_observation(tmp_path)


def test_event_must_be_finished_and_data_checked():
    assert event_readiness(_bootstrap(checked=False), 4)["ready"] is False


def test_event_rejects_same_gw_from_a_different_season():
    result = event_readiness(
        _bootstrap(), 4, expected_deadline="2027-09-10T17:30:00+00:00",
    )

    assert result["ready"] is False
    assert result["status"] == "deadline_mismatch"


def test_local_settlement_is_non_executable_and_requires_more_live_evidence(tmp_path: Path):
    _observation(tmp_path)
    observation, bundle, frozen = load_frozen_observation(tmp_path)
    boot, live = _bootstrap(), _event_live()
    payload = build_settlement(
        observation=observation, bundle=bundle, frozen_evidence=frozen,
        bootstrap=boot, bootstrap_raw=canonical_bytes(boot),
        event_live=live, event_live_raw=canonical_bytes(live),
        observed_at="2026-09-12T00:00:00+00:00",
    )

    assert payload["status"] == "settled"
    assert payload["production_writes"] == 0
    assert len(payload["code"]["live_settlement_sha256"]) == 64
    assert len(payload["code"]["strategy_shadow_sha256"]) == 64
    assert payload["settlement"]["selected_for_execution"] is False
    assert payload["gate"]["status"] == "insufficient_evidence"
    assert payload["gate"]["promotion_authorized"] is False
    assert payload["manual_evidence"]["source"] == "not_provided"


def test_public_picks_manual_score_is_auditable():
    live = _live()
    picks = []
    for position, row in enumerate(live, start=1):
        multiplier = 1 if position <= 11 else 0
        if row["element"] == 9:
            multiplier = 2
        picks.append({
            "element": row["element"], "position": position,
            "multiplier": multiplier, "is_captain": row["element"] == 9,
            "is_vice_captain": row["element"] == 8,
        })
    gross = sum(
        row["total_points"] * picks[index]["multiplier"]
        for index, row in enumerate(live)
    )
    payload = {
        "active_chip": None, "automatic_subs": [], "picks": picks,
        "entry_history": {"event": 4, "points": gross - 4,
                          "event_transfers_cost": 4},
    }

    manual, evidence = manual_from_public_picks(
        payload, live, season="2026-27", gw=4,
    )

    assert manual["actual_points"] == gross - 4
    assert manual["fingerprint"].startswith("public-picks:")
    assert evidence["reconciliation_delta"] == 0
    assert evidence["event_transfers_cost"] == 4
