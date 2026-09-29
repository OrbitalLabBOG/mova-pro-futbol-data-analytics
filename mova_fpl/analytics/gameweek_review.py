"""Cálculo puro del review retrospectivo contra resultados oficiales sellados."""

from __future__ import annotations

import json
from itertools import combinations
from pathlib import Path

import pandas as pd

from mova_fpl.engine.evaluate import collapse_results, score_decision
from mova_fpl.engine.state import Decision
from mova_fpl.rules import get as get_rules
from mova_fpl.rules.base import Position, Squad, SquadPlayer
from mova_fpl.rules.squad import is_valid_formation, validate_squad
from mova_fpl.rules.chips import effect
from mova_fpl.analytics.closeout_financing import tenths, validate_financing


def load_closeout_package(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    accepted = {
        "mova-fpl-manual-closeout-v1",
        "mova-fpl-autonomous-closeout-v1",
        "mova-fpl-autonomous-closeout-v2",
    }
    if payload.get("schema") not in accepted:
        raise ValueError("package de cierre no cumple un contrato soportado")
    for key in (
        "season", "gw", "deadline_at", "entry_id", "reviewed_at", "mounted_at",
        "trace_run_id", "decision_acta_path", "mount_evidence_path",
        "mount_evidence_sha256", "chip_inventory", "selected", "comparator",
        "intervention", "mount_verification", "proposals",
    ):
        if key not in payload:
            raise ValueError(f"package de cierre sin {key}")
    verification = payload["mount_verification"]
    if payload["schema"] == "mova-fpl-autonomous-closeout-v2":
        for name in ("selected", "comparator"):
            if not payload[name].get("financing"):
                raise ValueError(f"{name} sin financiación sellada")
    if not isinstance(verification, dict):
        raise ValueError("mount_verification debe ser un objeto")
    for key in ("squad", "xi", "captain", "vice_captain", "bench_order", "budget", "no_chip"):
        if key not in verification:
            raise ValueError(f"mount_verification sin {key}")
    return payload


def build_decision(spec: dict, season: str, gw: int) -> Decision:
    players = spec["players"]
    starters = tuple(int(row["element"]) for row in players if row["role"] == "starter")
    return Decision(
        season=season, gw=gw, squad_15=tuple(int(row["element"]) for row in players),
        starters=starters, captain=int(spec["captain"]),
        vice_captain=int(spec["vice_captain"]),
        bench_order=tuple(int(value) for value in spec["bench_order"]),
        expected_points=float(spec["expected_points"]), total_cost=float(spec["total_cost"]),
        bank_after=float(spec.get("bank_after", 0)), policy=str(spec["policy_version"]),
        transfers_in=tuple(int(value) for value in spec.get("transfers_in", ())),
        transfers_out=tuple(int(value) for value in spec.get("transfers_out", ())),
        hits=int(spec.get("hits", 0)), chip=spec.get("chip"),
        notes=tuple(spec.get("notes") or ()),
    )


def validate_decision(spec: dict, decision: Decision, official: dict, rules: dict) -> dict:
    current = {int(row["element"]): row for row in official["players"]}
    expected_ids = {int(row["element"]) for row in spec["players"]}
    missing = sorted(expected_ids - set(current))
    if missing:
        raise ValueError(f"elementos ausentes en artifact oficial: {missing}")
    for row in spec["players"]:
        observed = current[int(row["element"])]
        if str(row["name"]) != str(observed["web_name"]):
            raise ValueError(
                f"identidad cambió para {row['element']}: {row['name']} != {observed['web_name']}"
            )
        if Position.parse(row["position"]) != Position.parse(observed["element_type"]):
            raise ValueError(f"posición cambió para {row['name']}")
    squad = Squad(
        players=tuple(SquadPlayer(
            element=int(row["element"]), position=Position.parse(row["position"]),
            team=str(row["team"]), price=float(row["price"]),
        ) for row in spec["players"]),
        starters=decision.starters, captain=decision.captain,
        vice_captain=decision.vice_captain, bench_order=decision.bench_order,
        bank=decision.bank_after,
    )
    financed = spec.get("financing") is not None
    if financed:
        validate_financing(spec["financing"], decision)
        prices = spec["financing"]["market_prices_tenths"]
        if any(prices.get(str(row["element"])) != tenths(row["price"]) for row in spec["players"]):
            raise ValueError("precios de escenario no reproducen la financiación")
    violations = validate_squad(squad, rules, check_budget=not financed)
    if violations:
        raise ValueError("decisión inválida: " + "; ".join(
            f"{item.code}:{item.detail}" for item in violations
        ))
    return {row.element: {"position": row.position, "team": row.team, "price": row.price}
            for row in squad.players}


def score_scenario(spec: dict, decision: Decision, official: dict,
                   rules: dict) -> tuple[dict, list[dict]]:
    roster = validate_decision(spec, decision, official, rules)
    outcome = score_decision(decision, pd.DataFrame(official["live"]), rules, roster)
    minutes, points = collapse_results(pd.DataFrame(official["live"]))
    multipliers = dict(outcome.player_multipliers)
    chip_effect = effect(decision.chip)
    rows = []
    for row in spec["players"]:
        element = int(row["element"])
        multiplier = multipliers[element]
        rows.append({
            "element": element, "player_name": row["name"], "role": row["role"],
            "is_captain": element == decision.captain,
            "expected_points": float(row["expected_points"]),
            "p60": float(row["p60"]) if row.get("p60") is not None else None,
            "actual_points": int(points.get(element, 0)), "minutes": int(minutes.get(element, 0)),
            "multiplier": multiplier,
            "effective_points": int(points.get(element, 0)) * multiplier,
        })
    expected_total = sum(row["expected_points"] for row in rows
                         if chip_effect.scoring_players == "squad" or row["role"] == "starter")
    expected_total += (chip_effect.captain_multiplier - 1) * next(
        row["expected_points"] for row in rows if row["element"] == decision.captain)
    base_errors = [abs(row["expected_points"] - row["actual_points"]) for row in rows]
    p60_rows = [row for row in rows if row["p60"] is not None]
    brier = (sum((row["p60"] - int(row["minutes"] >= 60)) ** 2 for row in p60_rows)
             / len(p60_rows)) if p60_rows else None
    if sum(row["effective_points"] for row in rows) != outcome.points_before_hits:
        raise ValueError("atribución de puntos no reproduce el motor")
    return ({
        "points": outcome.points, "points_before_hits": outcome.points_before_hits,
        "captain_points": outcome.captain_points, "effective_captain": outcome.effective_captain,
        "auto_subs": [list(item) for item in outcome.auto_subs],
        "players_played": outcome.players_played, "expected_total_recomputed": round(expected_total, 2),
        "base_player_mae_15": round(sum(base_errors) / len(base_errors), 3),
        "p60_brier_15": round(brier, 4) if brier is not None else None,
        "p60_observations": len(p60_rows),
        "p60_unavailable_reason": None if p60_rows else "probabilities_missing",
        "financing_status": (validate_financing(spec["financing"], decision)["status"]
                             if spec.get("financing") else "legacy_initial_budget"),
        "chip": decision.chip, "hit_cost": decision.hits * int(rules["hit_cost"]),
    }, rows)


def hindsight_oracle(spec: dict, official: dict, rules: dict,
                     *, fixed_captain: int | None = None) -> int:
    _, points = collapse_results(pd.DataFrame(official["live"]))
    points = {int(row["element"]): int(points.get(int(row["element"]), 0))
              for row in spec["players"]}
    chip_effect = effect(spec.get("chip"))
    positions = {int(row["element"]): Position.parse(row["position"]) for row in spec["players"]}
    best = 0
    for xi in combinations(tuple(positions), 11):
        if not is_valid_formation([positions[element] for element in xi], rules):
            continue
        if fixed_captain is not None and fixed_captain not in xi:
            continue
        captain = fixed_captain if fixed_captain is not None else max(xi, key=lambda e: points[e])
        scoring = positions if chip_effect.scoring_players == "squad" else xi
        best = max(best, sum(points[element] for element in scoring)
                   + (chip_effect.captain_multiplier - 1) * points[captain])
    return best - int(spec.get("hits", 0)) * int(rules["hit_cost"])


def analyze_scenarios(package: dict, official: dict) -> dict:
    gw = int(package["gw"])
    rules = get_rules(package["season"]).SQUAD
    selected = build_decision(package["selected"], package["season"], gw)
    comparator = build_decision(package["comparator"], package["season"], gw)
    selected_score, selected_rows = score_scenario(
        package["selected"], selected, official, rules
    )
    comparator_score, comparator_rows = score_scenario(
        package["comparator"], comparator, official, rules
    )
    return {
        "rules": rules, "selected_decision": selected,
        "comparator_decision": comparator, "selected_score": selected_score,
        "comparator_score": comparator_score, "selected_rows": selected_rows,
        "comparator_rows": comparator_rows,
        "oracle_fixed": hindsight_oracle(
            package["selected"], official, rules, fixed_captain=selected.captain
        ),
        "oracle_free": hindsight_oracle(package["selected"], official, rules),
    }
