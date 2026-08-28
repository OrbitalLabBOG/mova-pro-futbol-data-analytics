"""Regresiones de presupuesto para los candidatos del ciclo vivo."""
from __future__ import annotations

from mova_fpl.cli.live import _engine_violations
from mova_fpl.engine.state import Candidate, Decision, State
from mova_fpl.rules import Position, Squad, SquadPlayer, get


def _players(*, appreciated: bool = False):
    positions = (
        [Position.GKP] * 2 + [Position.DEF] * 5
        + [Position.MID] * 5 + [Position.FWD] * 3
    )
    price = 6.7 if appreciated else 5.0
    purchase = 5.0
    return tuple(
        SquadPlayer(
            element=index, position=position, team=f"C{(index - 1) // 3}",
            price=price, purchase_price=purchase,
        )
        for index, position in enumerate(positions, start=1)
    )


def _state(players, *, bank=0.0, extras=()):
    candidates = tuple(
        Candidate(
            element=player.element, position=player.position, team=player.team,
            price=player.price, xp=1.0,
        )
        for player in players
    ) + tuple(extras)
    squad = Squad(
        players=players, starters=tuple(range(1, 12)), captain=1,
        vice_captain=2, bench_order=tuple(range(12, 16)), bank=bank,
    )
    return State(
        season="2026-27", gw=2, candidates=candidates, squad=squad,
        bank=bank, rules=get("2026-27").SQUAD,
    )


def _decision(players, *, bank_after=0.0, transfers_in=(), transfers_out=(), chip=None):
    ids = tuple(player.element for player in players)
    return Decision(
        season="2026-27", gw=2, squad_15=ids, starters=ids[:11],
        captain=ids[0], vice_captain=ids[1], bench_order=ids[11:],
        transfers_in=transfers_in, transfers_out=transfers_out, chip=chip,
        total_cost=round(sum(player.price for player in players), 1),
        bank_after=bank_after, policy="test",
    )


def test_appreciated_owned_squad_is_not_over_budget():
    players = _players(appreciated=True)  # 100.5M de valor actual, legal al conservarla.
    violations = _engine_violations(_decision(players), _state(players))

    assert not any(item["code"] == "BUDGET" for item in violations)
    assert not any(item["code"] == "BANK_RECONCILIATION" for item in violations)


def test_transfer_budget_uses_fpl_selling_price_and_bank():
    players = _players(appreciated=True)
    incoming = Candidate(
        element=99, position=Position.FWD, team="NEW", price=6.0, xp=2.0,
    )
    state = _state(players, bank=0.2, extras=(incoming,))
    changed = players[:-1] + (
        SquadPlayer(99, Position.FWD, "NEW", price=6.0),
    )
    # El jugador 15 se compro a 5.0 y vale 6.7: su venta da 5.8; con 0.2 de banco
    # alcanza exactamente para la compra de 6.0.
    decision = _decision(
        changed, bank_after=0.0, transfers_in=(99,), transfers_out=(15,),
    )

    violations = _engine_violations(decision, state)

    assert not any(item["code"] in {"BUDGET", "BANK_RECONCILIATION"}
                   for item in violations)


def test_negative_reconciled_bank_is_blocked_even_if_declared_nonnegative():
    players = _players(appreciated=True)
    incoming = Candidate(
        element=99, position=Position.FWD, team="NEW", price=6.1, xp=2.0,
    )
    state = _state(players, bank=0.2, extras=(incoming,))
    changed = players[:-1] + (
        SquadPlayer(99, Position.FWD, "NEW", price=6.1),
    )
    decision = _decision(
        changed, bank_after=0.0, transfers_in=(99,), transfers_out=(15,),
    )

    violations = _engine_violations(decision, state)

    assert any(item["code"] == "BUDGET" for item in violations)
