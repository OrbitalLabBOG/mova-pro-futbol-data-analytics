"""Liquidación reproducible del candidato estratégico en sombra."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest

from mova_fpl.analytics.strategy_shadow import (
    aggregate_strategy_shadow, settle_strategy_shadow,
)
from mova_fpl.engine.state import Decision
from mova_fpl.ops.review import _load_strategy_shadow


def _decision(captain: int) -> Decision:
    squad = tuple(range(1, 16))
    starters = (1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15)
    return Decision(
        season="2026-27", gw=4, squad_15=squad, starters=starters,
        captain=captain, vice_captain=9 if captain != 9 else 8,
        bench_order=(2, 6, 7, 12), expected_points=50.0,
        total_cost=75.0, bank_after=25.0, policy="milp",
    )


def _shadow() -> dict:
    control = _decision(8)
    candidate = _decision(9)
    control_xp = {element: element / 10.0 for element in range(1, 16)}
    candidate_xp = {element: element / 10.0 + 0.2 for element in range(1, 16)}
    candidate_sd = {element: 1.5 for element in range(1, 16)}
    return {
        "schema": "mova-strategy-shadow-v1",
        "experiment_id": "EXP-MOVA-2026-003",
        "strategy_key": "season_fixture_h3",
        "selected_for_execution": False,
        "virtual_trajectory": True,
        "trajectory": {"mode": "initialized_from_observed"},
        "chips": "disabled_in_both_arms",
        "control": {"decision": control.to_dict(), "violations": []},
        "candidate": {"decision": candidate.to_dict(), "violations": []},
        "projections": {
            "control_horizon_xp": {4: control_xp},
            "candidate_horizon_xp": {4: candidate_xp},
            "candidate_horizon_sd": {4: candidate_sd},
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
    points[8] = 2
    points[9] = 10
    return [
        {"element": element, "minutes": 90, "total_points": value}
        for element, value in points.items()
    ]


def test_settlement_scores_paired_policy_forecasts_and_manual_decision():
    result = settle_strategy_shadow(
        _shadow(), season="2026-27", gw=4, live=_live(), players=_players(),
        envelope_id="envelope_1", envelope_sha256="a" * 64,
        manual={"fingerprint": "manual", "expected_points": 49.0,
                "actual_points": 20},
    )

    assert result["status"] == "settled"
    assert result["selected_for_execution"] is False
    assert result["comparison"]["realized_points_delta"] == 8
    assert result["comparison"]["captain_changed"] is True
    assert result["candidate"]["forecast"]["rows"] == 15
    assert result["candidate"]["forecast"]["crps_normal"] >= 0
    assert result["manual"]["candidate_realized_delta"] == 11


def test_settlement_scores_optional_discrete_distribution_against_normal():
    shadow = _shadow()
    support = list(range(-6, 37))
    live = _live()
    actual = {row["element"]: row["total_points"] for row in live}
    rows = {}
    for element in range(1, 16):
        pmf = [0.0] * len(support)
        pmf[actual[element] - support[0]] = 1.0
        rows[str(element)] = {
            "optimization_xp": element / 10.0 + 0.2,
            "pmf": pmf,
        }
    shadow["projections"]["candidate_current_distribution"] = {
        "schema": "mova-discrete-shadow-v1",
        "experiment_id": "EXP-MOVA-2026-006",
        "artifact_sha256": "d" * 64,
        "support": support,
        "rows": rows,
        "row_count": len(rows),
        "optimization_mean_unchanged": True,
        "selected_for_execution": False,
    }

    result = settle_strategy_shadow(
        shadow, season="2026-27", gw=4, live=live, players=_players(),
    )

    discrete = result["candidate"]["forecast"]["discrete"]
    assert discrete["candidate"]["crps_discrete"] == 0.0
    assert discrete["candidate"]["zero_brier"] == 0.0
    assert discrete["crps_delta_vs_normal"] < 0


def test_settlement_rejects_any_execution_authority():
    shadow = _shadow()
    shadow["selected_for_execution"] = True

    with pytest.raises(ValueError, match="no ejecutable"):
        settle_strategy_shadow(
            shadow, season="2026-27", gw=4, live=_live(), players=_players(),
        )


def test_three_consecutive_settlements_require_human_review_not_auto_promotion():
    base = settle_strategy_shadow(
        _shadow(), season="2026-27", gw=4, live=_live(), players=_players(),
    )
    rows = []
    for gw, delta in ((4, 8), (5, -2), (6, 4)):
        row = deepcopy(base)
        row["gw"] = gw
        row["trajectory"]["mode"] = (
            "initialized_from_observed" if gw == 4 else "carried_from_previous"
        )
        row["comparison"]["realized_points_delta"] = delta
        rows.append(row)

    gate = aggregate_strategy_shadow(rows)

    assert gate["status"] == "review_required"
    assert gate["promotion_authorized"] is False
    assert gate["gameweeks"] == [4, 5, 6]
    assert gate["policy"] == {
        "candidate_points_delta": 10,
        "mean_delta": pytest.approx(10 / 3, abs=0.001),
        "wins": 2, "losses": 1, "ties": 0, "action_changes": 3,
    }
    assert gate["next_action"] == "socialize_and_request_explicit_human_decision"


def test_gap_resets_the_consecutive_evidence_streak():
    base = settle_strategy_shadow(
        _shadow(), season="2026-27", gw=4, live=_live(), players=_players(),
    )
    first, third = deepcopy(base), deepcopy(base)
    first["gw"], third["gw"] = 4, 6
    third["trajectory"]["mode"] = "carried_from_previous"

    gate = aggregate_strategy_shadow([first, third])

    assert gate["status"] == "insufficient_evidence"
    assert gate["gameweeks"] == [6]
    assert gate["promotion_authorized"] is False


def test_invalid_latest_observation_resets_the_evidence_streak():
    base = settle_strategy_shadow(
        _shadow(), season="2026-27", gw=4, live=_live(), players=_players(),
    )
    rows = []
    for gw in (4, 5, 6):
        row = deepcopy(base)
        row["gw"] = gw
        row["trajectory"]["mode"] = (
            "initialized_from_observed" if gw == 4 else "carried_from_previous"
        )
        rows.append(row)
    rows.append({"season": "2026-27", "gw": 7, "status": "invalid"})

    gate = aggregate_strategy_shadow(rows)

    assert gate["status"] == "insufficient_evidence"
    assert gate["gameweeks"] == []
    assert gate["promotion_authorized"] is False


class _EnvelopeDB:
    def __init__(self, row):
        self.row = row

    def latest_decision_envelope(self, cycle_id):
        assert cycle_id == "2026-27-gw04"
        return self.row


def test_shadow_loader_verifies_envelope_file_hash(tmp_path):
    payload = {"content_sha256": "c" * 64, "strategy_shadow": _shadow()}
    path = tmp_path / "envelope.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    row = {
        "envelope_id": "envelope_1", "artifact_path": str(path),
        "artifact_sha256": digest, "content_sha256": "c" * 64,
    }

    loaded = _load_strategy_shadow(_EnvelopeDB(row), "2026-27-gw04")

    assert loaded["status"] == "ready"
    assert loaded["shadow"]["strategy_key"] == "season_fixture_h3"

    tampered = _load_strategy_shadow(
        _EnvelopeDB({**row, "artifact_sha256": "0" * 64}), "2026-27-gw04"
    )
    assert tampered["status"] == "invalid"
    assert tampered["reason"] == "envelope_artifact_sha256_mismatch"
