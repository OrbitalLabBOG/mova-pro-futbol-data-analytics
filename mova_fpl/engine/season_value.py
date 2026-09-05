"""Learned joint chip inventory value, evaluated through the season's last GW.

Bellman recursion uses E[max(action value)] for an opportunity observed *then*,
not a maximum over a path of future match results known today. Reward vectors
are paired historical pre-deadline solver deltas, preserving chip competition.
This is an approximate inventory state, not a full player-state world model.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from functools import lru_cache

import numpy as np

from mova_fpl.engine.planner import ChipVerdict, chip_value, structure_factor
from mova_fpl.optimizer.milp import Infeasible, solve
from mova_fpl.rules.chips import used_in_window

CHIPS = ("bench_boost", "free_hit", "triple_captain", "wildcard")


@dataclass
class SeasonValueModel:
    version: str = "1.0.0"
    samples: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def fit(self, rows: list[dict], *, target_season: str):
        if not rows or any(str(r["season"]) >= target_season for r in rows):
            raise ValueError("chip opportunities must come from prior seasons")
        rewards = np.asarray([[r["values"][c] for c in CHIPS] for r in rows], dtype=float)
        if not np.isfinite(rewards).all():
            raise ValueError("non-finite chip value")
        self.samples = rows
        self.metadata = {"target_season": target_season, "rows": len(rows),
                         "train_seasons": sorted({r["season"] for r in rows}),
                         "state_contract": "joint-chip-inventory-v1",
                         "limitations": ["stationary normalized opportunity distribution",
                                         "squad transitions approximated by historical samples",
                                         "not a full-season player-state simulator"]}
        return self

    def choose(self, state, values: dict) -> tuple[str | None, dict]:
        if not self.samples:
            raise ValueError("chip value model is not fitted")
        if any(s >= state.season for s in self.metadata["train_seasons"]):
            raise ValueError("chip model fitted on target/future season")
        catalogue = state.chips
        if catalogue is None:
            return None, {"reason": "no chip catalogue"}
        if catalogue.per_window != 1:
            raise ValueError("inventory-v1 supports one of each chip per window")
        windows = catalogue.windows
        end = max(w.last_gw for w in windows)
        full_mask = sum(1 << i for i, c in enumerate(CHIPS) if c in catalogue.chips)
        current_window = catalogue.window_for(state.gw)
        if current_window is None:
            return None, {"reason": "outside chip windows"}
        used = used_in_window(state.chips_used, current_window)
        mask = sum(1 << i for i, c in enumerate(CHIPS)
                   if c in catalogue.chips and used.get(c, 0) == 0)
        raw = np.asarray([[max(0., float(r["values"][c])) /
                           max(float(r.get("structure", {}).get(c, 1.)), 1e-9)
                           for c in CHIPS] for r in self.samples])
        # A deterministic bounded support; no random resampling per solve.
        if len(raw) > 128:
            raw = raw[np.linspace(0, len(raw) - 1, 128, dtype=int)]

        visible_gws = {int(g) for _, g in state.schedule}

        def factor(chip, gw):
            # Missing distant fixtures mean unknown, never a confirmed blank.
            return structure_factor(chip, gw, state.schedule) if gw in visible_gws else 1.

        def next_mask(gw, remaining):
            old, new = catalogue.window_for(gw), catalogue.window_for(gw + 1)
            return full_mask if new is not None and new != old else remaining

        def legal(gw, remaining, previous_fh):
            if catalogue.window_for(gw) is None:
                return []
            return [i for i, chip in enumerate(CHIPS)
                    if remaining & (1 << i) and gw not in catalogue.unavailable_gws(chip)
                    and not (chip == "free_hit" and previous_fh)]

        @lru_cache(None)
        def continuation(gw, remaining, previous_fh):
            if gw > end:
                return 0.
            hold = continuation(gw + 1, next_mask(gw, remaining), False)
            choices = [np.full(len(raw), hold)]
            for i in legal(gw, remaining, previous_fh):
                c = CHIPS[i]
                future = continuation(gw + 1, next_mask(gw, remaining & ~(1 << i)),
                                      c == "free_hit")
                choices.append(raw[:, i] * factor(c, gw) + future)
            return float(np.max(np.vstack(choices), axis=0).mean())

        hold = continuation(state.gw + 1, next_mask(state.gw, mask), False)
        actions = {"hold": hold}
        for chip in sorted(state.chips_available()):
            if chip not in values or chip not in CHIPS:
                continue
            i = CHIPS.index(chip)
            actions[chip] = float(values[chip]) + continuation(
                state.gw + 1, next_mask(state.gw, mask & ~(1 << i)), chip == "free_hit")
        best = max(actions, key=actions.get)
        selected = None if best == "hold" or actions[best] <= hold + 1e-8 else best
        return selected, {"schema": "mova-season-value-v1", "through_gw": end,
                          "q_values": actions, "hold_value": hold,
                          "selected": selected, "model_version": self.version,
                          "support_size": len(raw), "bellman_states": continuation.cache_info().currsize,
                          "objective": "expected chip incremental points, undiscounted"}


def opportunity_values(state, xp_matrix, ocfg, *, replenish=False):
    """Value each legal chip from the same state and projection. No realized points."""
    clean = replace(state, chips_allowed={}, chips_used=() if replenish else state.chips_used)
    base = solve(clean, xp_matrix, replace(ocfg, tie_break=0., chip_epsilon=0.))
    values, extras = {}, {}
    for chip in sorted(clean.chips_available()):
        try:
            values[chip], extras[chip] = chip_value(clean, xp_matrix, chip, ocfg, base.objective)
        except Infeasible:
            continue
    return values, extras


def plan_season_value(state, xp_matrix, ocfg, model: SeasonValueModel):
    if state.is_cold_start or not state.chips_available():
        return ChipVerdict(state.gw, None, 0., 0., "no available chip opportunity")
    values, extras = opportunity_values(state, xp_matrix, ocfg)
    selected, evidence = model.choose(state, values)
    hold = evidence["hold_value"]
    threshold = (float(values[selected]) - (evidence["q_values"][selected] - hold)
                 if selected else 0.)
    import json
    return ChipVerdict(state.gw, selected, float(values.get(selected, 0.)), threshold,
                       json.dumps(evidence, sort_keys=True), values, extras.get(selected))
