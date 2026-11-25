"""Legal causal decision replay calling mova_fpl.engine.runner.decide + milp + score_decision."""
from __future__ import annotations

import time
from dataclasses import replace
from typing import Any

import numpy as np
import pandas as pd

from experiments.recency_eb.data import (
    build_results,
    build_roster,
    causal_history,
    team_schedule_counts,
)
from mova_fpl.engine.evaluate import collapse_results, score_decision
from mova_fpl.engine.projection import _proba_minutos
from mova_fpl.engine.runner import Config, decide
from mova_fpl.engine.state import Candidate, State
from mova_fpl.optimizer.horizon import build_xp_matrix
from mova_fpl.rules import get as get_rules
from mova_fpl.rules.base import Position, Squad, SquadPlayer
from mova_fpl.rules.market import accumulate_free_transfers


def _make_candidates(roster: pd.DataFrame, xp: np.ndarray) -> tuple[Candidate, ...]:
    out = []
    for r, v in zip(roster.itertuples(index=False), xp):
        if pd.isna(r.position) or pd.isna(r.team) or pd.isna(r.value):
            continue
        out.append(Candidate(
            element=int(r.element),
            position=Position.parse(str(r.position)),
            team=str(r.team),
            price=float(r.value) / 10.0,
            xp=float(v),
            name=str(r.name),
        ))
    return tuple(out)


def _squad_from_decision(decision, conocidos: dict, bank: float) -> Squad:
    players = tuple(
        SquadPlayer(
            element=e,
            position=conocidos[e]["position"],
            team=conocidos[e]["team"],
            price=conocidos[e]["price"],
            purchase_price=conocidos[e].get("purchase_price", conocidos[e]["price"]),
        )
        for e in decision.squad_15
    )
    return Squad(
        players=players,
        starters=decision.starters,
        captain=decision.captain,
        vice_captain=decision.vice_captain,
        bench_order=decision.bench_order,
        bank=bank,
    )


def _bench_points(decision, outcome, results: pd.DataFrame) -> int:
    _, puntos = collapse_results(results)
    mult_map = dict(outcome.player_multipliers)
    return int(sum(int(puntos.get(e, 0)) for e in decision.squad_15 if mult_map.get(e, 0) == 0))


def replay_season_arm(
    *,
    arm_name: str,
    season: str,
    prev_df: pd.DataFrame,
    curr_df: pd.DataFrame,
    schedule_source: pd.DataFrame,
    equipos: dict[int, str],
    minutes_model,
    points_model,
    gws: list[int],
    max_calendar_gw: int,
    initial_squad: Squad | None = None,
    lock_gw1_squad: bool = False,
    time_limit: int = 15,
    minutes_cache: dict[int, tuple[pd.DataFrame, np.ndarray]] | None = None,
    verbose: bool = True,
) -> dict[str, Any]:
    """Run a single causal MILP walk-forward replay arm with identical policy config.

    - `minutes_cache`: optional shared cache of (roster, minutes_proba) per GW so both arms
      use the exact same frozen MinutesModel 1.1.0 probabilities without redundant tree calls.
    - When `initial_squad` is provided and `lock_gw1_squad=True` (2026-27 from Julian's GW1 15),
      GW1 sets `current_transfer_limit=0` so MILP picks XI/C/VC/bench only; transfers start GW2
      with `free_transfers=1` and separate ledgers per arm.
    """
    t0 = time.perf_counter()
    rules_mod = get_rules(season)
    rules = rules_mod.SQUAD
    scoring = rules_mod.SCORING
    umbrales = scoring.defcon_thresholds

    base_cfg = Config(
        policy="milp",
        projector="points",
        horizon=3,
        decay=0.84,
        bench_weight=0.12,
        top_k=30,
        max_hits=2,
        chip_policy="none",
        time_limit=int(time_limit),
        seed=42,
    )

    conocidos: dict[int, dict] = {}
    squad: Squad | None = initial_squad
    bank: float = float(initial_squad.bank) if initial_squad is not None else 0.0
    free_transfers: int = 1
    if initial_squad is not None:
        for p in initial_squad.players:
            conocidos[p.element] = {
                "position": p.position,
                "team": p.team,
                "price": p.price,
                "purchase_price": p.purchase_price if p.purchase_price is not None else p.price,
            }

    gw_records = []
    for gw in gws:
        hist = causal_history(prev_df, curr_df, gw)
        if minutes_cache is not None and gw in minutes_cache:
            roster, proba = minutes_cache[gw]
        else:
            roster = build_roster(curr_df, gw)
            proba = _proba_minutos(hist, roster, minutes_model)
            if minutes_cache is not None:
                minutes_cache[gw] = (roster, proba)

        if roster.empty:
            continue

        pred = points_model.project(hist, roster, proba, scoring, umbrales, equipos=equipos)
        xp_arr = pred["xp"].to_numpy(dtype=float)
        candidatos = _make_candidates(roster, xp_arr)
        if len(candidatos) < rules["size"]:
            continue

        # Legal horizon lookahead using published calendar only
        hasta = min(max_calendar_gw, gw + base_cfg.horizon - 1)
        conteo = team_schedule_counts(schedule_source, gw, hasta)
        horizon_xp = build_xp_matrix(candidatos, conteo, gw, hasta - gw + 1, decay=base_cfg.decay)

        state = State(
            season=season,
            gw=gw,
            candidates=candidatos,
            squad=squad,
            free_transfers=free_transfers,
            bank=bank,
            rules=rules,
            horizon_xp=horizon_xp,
            chips=None,
            chips_used=(),
            schedule={},
        )

        # In 2026-27 GW1, Julian's squad is fixed: XI/captain/VC/bench only (0 transfers).
        if lock_gw1_squad and gw == 1:
            gw_cfg = replace(base_cfg, current_transfer_limit=0, max_hits=0)
        else:
            gw_cfg = base_cfg

        decision = decide(gw, state, gw_cfg)

        owned = {p.element for p in squad.players} if squad is not None else set()
        bought = set(int(e) for e in decision.transfers_in)
        for c in candidatos:
            prev = conocidos.get(c.element, {})
            if c.element in bought:
                purchase = c.price
            elif c.element in owned and prev.get("purchase_price") is not None:
                purchase = prev["purchase_price"]
            else:
                purchase = prev.get("purchase_price", c.price)
            conocidos[c.element] = {
                "position": c.position,
                "team": c.team,
                "price": c.price,
                "purchase_price": purchase,
            }

        resultados = build_results(curr_df, gw)
        outcome = score_decision(decision, resultados, rules, conocidos)
        bench_pts = _bench_points(decision, outcome, resultados)
        hit_cost = int(decision.hits) * int(rules["hit_cost"])

        name_by_el = {c.element: c.name for c in candidatos}
        gw_records.append({
            "gw": int(gw),
            "points": int(outcome.points),
            "points_before_hits": int(outcome.points_before_hits),
            "hits": int(decision.hits),
            "hit_cost": hit_cost,
            "captain": decision.captain,
            "captain_name": name_by_el.get(decision.captain, str(decision.captain)),
            "effective_captain": outcome.effective_captain,
            "captain_points": int(outcome.captain_points),
            "bench_points": bench_pts,
            "auto_subs": len(outcome.auto_subs),
            "transfers_count": len(decision.transfers_in),
            "transfers_in": [int(e) for e in decision.transfers_in],
            "transfers_out": [int(e) for e in decision.transfers_out],
            "transfers_in_names": [name_by_el.get(e, str(e)) for e in decision.transfers_in],
            "transfers_out_names": [name_by_el.get(e, str(e)) for e in decision.transfers_out],
            "expected_points": round(float(decision.expected_points), 2),
            "bank_after": round(float(decision.bank_after), 1),
            "free_transfers_before": int(free_transfers),
        })

        # Ledger progression (matches simulator.py exact rules)
        was_cold_or_locked_gw1 = (squad is None) or (lock_gw1_squad and gw == 1)
        bank = float(decision.bank_after)
        squad = _squad_from_decision(decision, conocidos, bank)
        if was_cold_or_locked_gw1:
            free_transfers = 1
        else:
            free_transfers = accumulate_free_transfers(
                free_transfers, len(decision.transfers_in), rules["max_free_transfers"],
            )

    elapsed = round(time.perf_counter() - t0, 2)
    totals = {
        "total_points": int(sum(r["points"] for r in gw_records)),
        "total_points_before_hits": int(sum(r["points_before_hits"] for r in gw_records)),
        "total_hits": int(sum(r["hits"] for r in gw_records)),
        "total_hit_cost": int(sum(r["hit_cost"] for r in gw_records)),
        "total_captain_points": int(sum(r["captain_points"] for r in gw_records)),
        "total_bench_points": int(sum(r["bench_points"] for r in gw_records)),
        "total_transfers": int(sum(r["transfers_count"] for r in gw_records)),
        "total_auto_subs": int(sum(r["auto_subs"] for r in gw_records)),
    }
    if verbose:
        print(
            f"[replay {season} {arm_name}] total={totals['total_points']} pts "
            f"(before_hits={totals['total_points_before_hits']}, hits={totals['total_hits']} / -{totals['total_hit_cost']}, "
            f"cap={totals['total_captain_points']}, bench={totals['total_bench_points']}, "
            f"xfers={totals['total_transfers']}) [{elapsed}s]",
            flush=True,
        )
    return {
        "arm": arm_name,
        "season": season,
        "gws": [int(g) for g in gws],
        "config": {
            "policy": base_cfg.policy,
            "horizon": base_cfg.horizon,
            "decay": base_cfg.decay,
            "bench_weight": base_cfg.bench_weight,
            "top_k": base_cfg.top_k,
            "max_hits": base_cfg.max_hits,
            "chip_policy": base_cfg.chip_policy,
            "time_limit": base_cfg.time_limit,
            "lock_gw1_squad": lock_gw1_squad,
        },
        "runtime_seconds": elapsed,
        "totals": totals,
        "by_gw": gw_records,
    }


def summarize_julian_actual(julian_history: dict, max_gw: int = 11) -> dict[str, Any]:
    """Summarize Julian's real 2026-27 GW1-11 performance (human reference only)."""
    current = [row for row in julian_history.get("current", []) if int(row["event"]) <= max_gw]
    by_gw = [
        {
            "gw": int(r["event"]),
            "points": int(r["points"]) - int(r["event_transfers_cost"]),
            "points_before_hits": int(r["points"]),
            "hit_cost": int(r["event_transfers_cost"]),
            "transfers_count": int(r["event_transfers"]),
            "bench_points": int(r["points_on_bench"]),
            "bank": round(float(r["bank"]) / 10.0, 1),
            "value": round(float(r["value"]) / 10.0, 1),
            "total_points_cumulative": int(r["total_points"]),
        }
        for r in current
    ]
    return {
        "entry_id": 3609854,
        "chips_used": julian_history.get("chips", []),
        "totals": {
            "total_points": int(by_gw[-1]["total_points_cumulative"]) if by_gw else 0,
            "total_points_sum_check": int(sum(r["points"] for r in by_gw)),
            "total_hit_cost": int(sum(r["hit_cost"] for r in by_gw)),
            "total_bench_points": int(sum(r["bench_points"] for r in by_gw)),
            "total_transfers": int(sum(r["transfers_count"] for r in by_gw)),
        },
        "by_gw": by_gw,
    }
