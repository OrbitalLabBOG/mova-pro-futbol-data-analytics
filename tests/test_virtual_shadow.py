"""Ledger de squad/banco/FT para trayectorias de shadow multi-GW."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json

import pytest

from mova_fpl.cli.live import _prior_virtual_states
from mova_fpl.engine.state import Candidate, Decision, State
from mova_fpl.engine.virtual_shadow import next_virtual_state, restore_virtual_state
from mova_fpl.rules import get as get_rules
from mova_fpl.rules.base import Position, Squad, SquadPlayer


POSITIONS = (
    [Position.GKP] * 2 + [Position.DEF] * 5
    + [Position.MID] * 5 + [Position.FWD] * 4
)


def _boot(price_tenths=50):
    return {
        "teams": [{"id": i, "name": f"T{i}"} for i in range(1, 8)],
        "elements": [
            {"id": element, "element_type": position.value,
             "team": 1 + (element - 1) // 3, "now_cost": price_tenths + element}
            for element, position in zip(range(1, 17), POSITIONS)
        ],
    }


def _state(*, gw=4, squad=True):
    candidates = tuple(
        Candidate(
            element=element, position=position, team=f"T{1 + (element - 1) // 3}",
            price=(50 + element) / 10.0, xp=2.0,
        )
        for element, position in zip(range(1, 17), POSITIONS)
    )
    owned = tuple(
        SquadPlayer(
            element=item.element, position=item.position, team=item.team,
            price=item.price, purchase_price=round(item.price - 0.5, 1),
        )
        for item in candidates[:15]
    )
    return State(
        season="2026-27", gw=gw, candidates=candidates,
        squad=Squad(players=owned, bank=1.0) if squad else None,
        bank=1.0, free_transfers=3, rules=get_rules("2026-27").SQUAD,
    )


def _decision() -> Decision:
    squad = tuple(range(2, 17))
    return Decision(
        season="2026-27", gw=4, squad_15=squad, starters=squad[:11],
        captain=2, vice_captain=3, bench_order=squad[11:],
        transfers_in=(16,), transfers_out=(1,), hits=0,
        total_cost=90.0, bank_after=0.4, expected_points=50.0, policy="milp",
    )


def test_virtual_state_roundtrip_preserves_purchase_price_and_free_transfers():
    state = _state()
    spec = next_virtual_state(
        _decision(), state=state, boot=_boot(),
        strategy_key="season_fixture_h3", arm="candidate",
    )
    next_base = replace(_state(gw=5), squad=None, bank=0.0, free_transfers=1)

    restored = restore_virtual_state(
        spec, base_state=next_base, boot=_boot(price_tenths=60),
        expected_strategy="season_fixture_h3", expected_arm="candidate",
        expected_previous_gw=4,
    )

    by_id = {player.element: player for player in restored.squad.players}
    assert restored.bank == pytest.approx(0.4)
    assert restored.free_transfers == 3
    assert by_id[2].purchase_price == pytest.approx(4.7)
    assert by_id[2].price == pytest.approx(6.2)
    assert by_id[16].purchase_price == pytest.approx(6.6)


def test_virtual_state_rejects_tampering_and_arm_swap():
    spec = next_virtual_state(
        _decision(), state=_state(), boot=_boot(),
        strategy_key="season_fixture_h3", arm="candidate",
    )
    spec["bank"] = 99.0

    with pytest.raises(ValueError, match="fingerprint"):
        restore_virtual_state(
            spec, base_state=_state(gw=5), boot=_boot(),
            expected_strategy="season_fixture_h3", expected_arm="candidate",
            expected_previous_gw=4,
        )

    valid = next_virtual_state(
        _decision(), state=_state(), boot=_boot(),
        strategy_key="season_fixture_h3", arm="candidate",
    )
    with pytest.raises(ValueError, match="otro brazo"):
        restore_virtual_state(
            valid, base_state=_state(gw=5), boot=_boot(),
            expected_strategy="season_fixture_h3", expected_arm="control",
            expected_previous_gw=4,
        )


def test_cold_start_opens_next_gameweek_with_one_free_transfer():
    spec = next_virtual_state(
        _decision(), state=_state(squad=False), boot=_boot(),
        strategy_key="season_fixture_h3", arm="candidate",
    )
    assert spec["free_transfers"] == 1


def test_prior_envelope_must_be_hashed_and_consecutive(tmp_path):
    control = next_virtual_state(
        _decision(), state=_state(), boot=_boot(),
        strategy_key="season_fixture_h3", arm="control",
    )
    candidate = next_virtual_state(
        _decision(), state=_state(), boot=_boot(),
        strategy_key="season_fixture_h3", arm="candidate",
    )
    envelope = {
        "envelope_id": "envelope_4",
        "strategy_shadow": {
            "strategy_key": "season_fixture_h3", "season": "2026-27", "gw": 4,
            "next_state": {"control": control, "candidate": candidate},
        },
    }
    path = tmp_path / "gw04-envelope.json"
    path.write_text(json.dumps(envelope), encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()

    states, continuity = _prior_virtual_states(
        str(path), digest, season="2026-27", gw=5,
    )

    assert states["candidate"]["arm"] == "candidate"
    assert continuity["mode"] == "carried_from_previous"

    reset, reset_reason = _prior_virtual_states(
        str(path), digest, season="2026-27", gw=6,
    )
    assert reset is None
    assert reset_reason["mode"] == "initialized_from_observed"

    with pytest.raises(ValueError, match="SHA-256"):
        _prior_virtual_states(str(path), "0" * 64, season="2026-27", gw=5)


@pytest.mark.parametrize('chip', ['free_hit', 'wildcard', 'bench_boost', 'triple_captain'])
def test_joint_virtual_inventory_preserves_chip_semantics(chip):
    state = replace(_state(), chips=get_rules('2026-27').CHIPS)
    decision = replace(_decision(), chip=chip)
    spec = next_virtual_state(decision, state=state, boot=_boot(),
                              strategy_key='season_value_v2', arm='candidate')
    restored = restore_virtual_state(spec, base_state=replace(state, gw=5), boot=_boot(),
        expected_strategy='season_value_v2', expected_arm='candidate', expected_previous_gw=4)
    assert chip not in restored.chips_available()
    if chip == 'free_hit':
        assert {p.element for p in restored.squad.players} == {p.element for p in state.squad.players}
        assert restored.bank == state.bank
    else:
        assert {p.element for p in restored.squad.players} == set(decision.squad_15)
    assert restored.free_transfers == (4 if chip in {'free_hit', 'wildcard'} else 3)
