"""Estado virtual de una política en shadow a través de varias gameweeks."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace

from mova_fpl.engine.state import Decision, State
from mova_fpl.rules.base import Position, Squad, SquadPlayer
from mova_fpl.rules.market import accumulate_free_transfers
from mova_fpl.rules.chips import ChipUse, validate_chip

SCHEMA = "mova-strategy-virtual-state-v1"


def canonical_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
    )


def state_fingerprint(payload: dict) -> str:
    body = {key: value for key, value in payload.items() if key != "state_fingerprint"}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def restore_virtual_state(spec: dict, *, base_state: State, boot: dict,
                          expected_strategy: str, expected_arm: str,
                          expected_previous_gw: int) -> State:
    """Restaura squad/banco/FT, refrescando precio y club desde bootstrap vivo."""
    if spec.get("schema") != SCHEMA:
        raise ValueError("estado virtual incompatible")
    if spec.get("strategy_key") != expected_strategy:
        raise ValueError("estado virtual pertenece a otra estrategia")
    if spec.get("arm") != expected_arm:
        raise ValueError("estado virtual pertenece a otro brazo")
    if str(spec.get("season")) != base_state.season:
        raise ValueError("estado virtual pertenece a otra temporada")
    if int(spec.get("applied_gw", 0)) != int(expected_previous_gw):
        raise ValueError("estado virtual no es de la jornada inmediatamente anterior")
    if spec.get("state_fingerprint") != state_fingerprint(spec):
        raise ValueError("fingerprint del estado virtual no coincide")
    if expected_strategy == "season_value_v2":
        if "chips_used" not in spec or base_state.chips is None:
            raise ValueError("missing virtual chip inventory")
        used = []
        for raw in spec["chips_used"]:
            use = ChipUse(**raw)
            if (use.gw > expected_previous_gw or use.gw < 1
                    or validate_chip(use.chip, use.gw, tuple(used), base_state.chips)):
                raise ValueError("invalid virtual chip history")
            used.append(use)

    catalog = {int(item["id"]): item for item in boot["elements"]}
    teams = {int(item["id"]): str(item["name"]) for item in boot["teams"]}
    players = []
    for stored in spec.get("squad") or ():
        element = int(stored["element"])
        item = catalog.get(element)
        if item is None:
            raise ValueError(f"elemento virtual ausente del bootstrap: {element}")
        position = Position.parse(item["element_type"])
        players.append(SquadPlayer(
            element=element,
            position=position,
            team=teams.get(int(item["team"]), str(item["team"])),
            price=float(item["now_cost"]) / 10.0,
            purchase_price=float(stored["purchase_price"]),
        ))
    if len(players) != int(base_state.rules["size"]):
        raise ValueError(f"estado virtual tiene {len(players)} jugadores")
    bank = float(spec["bank"])
    free_transfers = int(spec["free_transfers"])
    if bank < 0 or not 1 <= free_transfers <= int(base_state.rules["max_free_transfers"]):
        raise ValueError("banco o transferencias libres inválidos en estado virtual")
    return replace(
        base_state,
        squad=Squad(players=tuple(players), bank=bank),
        bank=bank,
        free_transfers=free_transfers,
        chips_allowed={},
        chips_used=(tuple(ChipUse(**u) for u in spec["chips_used"])
                    if "chips_used" in spec else base_state.chips_used),
    )


def next_virtual_state(decision: Decision, *, state: State, boot: dict,
                       strategy_key: str, arm: str) -> dict:
    """Aplica solo la primera acción y sella el estado que abrirá la siguiente GW."""
    with_chips = strategy_key == "season_value_v2"
    if decision.chip is not None and not with_chips:
        raise ValueError("el estado virtual aislado no admite chips")
    if with_chips and decision.chip and (
            state.chips is None or validate_chip(decision.chip, state.gw, state.chips_used, state.chips)):
        raise ValueError("illegal virtual chip")
    if arm not in {"control", "candidate"}:
        raise ValueError(f"brazo virtual desconocido: {arm}")
    catalog = {int(item["id"]): item for item in boot["elements"]}
    previous = {
        player.element: player for player in (state.squad.players if state.squad else ())
    }
    squad = []
    elements = previous if decision.chip == "free_hit" else decision.squad_15
    for element in sorted(elements):
        item = catalog.get(int(element))
        if item is None:
            raise ValueError(f"elemento decidido ausente del bootstrap: {element}")
        current_price = float(item["now_cost"]) / 10.0
        owned = previous.get(int(element))
        purchase_price = (
            float(owned.purchase_price)
            if owned is not None and owned.purchase_price is not None
            else current_price
        )
        squad.append({
            "element": int(element),
            "purchase_price": round(purchase_price, 1),
        })
    if state.squad is None:
        next_free_transfers = 1
    else:
        next_free_transfers = accumulate_free_transfers(
            state.free_transfers,
            len(decision.transfers_in),
            int(state.rules["max_free_transfers"]),
        )
        if decision.chip in {"wildcard", "free_hit"}:
            next_free_transfers = min(state.free_transfers + 1, int(state.rules["max_free_transfers"]))
    body = {
        "schema": SCHEMA,
        "strategy_key": strategy_key,
        "arm": arm,
        "season": decision.season,
        "applied_gw": int(decision.gw),
        "decision_fingerprint": decision.fingerprint(),
        "squad": squad,
        "bank": round(float(state.bank if decision.chip == "free_hit" else decision.bank_after), 1),
        "free_transfers": int(next_free_transfers),
    }
    if with_chips:
        used = list(state.chips_used)
        if decision.chip:
            used.append(ChipUse(state.gw, decision.chip))
        body["chips_used"] = [{"gw": u.gw, "chip": u.chip} for u in used]
    return {**body, "state_fingerprint": state_fingerprint(body)}
