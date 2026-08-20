from __future__ import annotations

import pandas as pd
import pytest

from mova_fpl.cli.review_squad import build_decision


def _frames():
    positions = (["GKP", "GKP"] + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3)
    roster = pd.DataFrame({
        "element": range(1, 16), "position": positions,
        "value": [45] * 15, "team": [f"T{i}" for i in range(1, 16)],
    })
    detail = pd.DataFrame({"element": range(1, 16), "xp": [float(i) for i in range(1, 16)]})
    return roster, detail


def _spec():
    return {
        "season": "2026-27", "gw": 1, "squad": list(range(1, 16)),
        "starters": [1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15],
        "captain": 15, "vice_captain": 14, "bench_order": [2, 12, 7, 6],
    }


def test_build_reviewed_decision_is_deterministic():
    roster, detail = _frames()
    decision = build_decision(_spec(), roster, detail, 100.0)
    assert decision.policy == "human-reviewed"
    assert decision.expected_points == 108.0
    assert decision.total_cost == 67.5
    assert decision.bank_after == 32.5


def test_build_reviewed_decision_rejects_incomplete_bench():
    roster, detail = _frames()
    spec = _spec()
    spec["bench_order"] = spec["bench_order"][:-1]
    with pytest.raises(ValueError, match="complemento"):
        build_decision(spec, roster, detail, 100.0)
