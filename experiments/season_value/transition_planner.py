"""Experimental Markov opportunity Bellman planner; no production registration."""
from functools import lru_cache

import numpy as np

from experiments.season_value.transition import OpportunityTransition
from mova_fpl.engine.planner import structure_factor
from mova_fpl.engine.season_value import CHIPS, SeasonValueModel
from mova_fpl.rules.chips import used_in_window


class MarkovSeasonValue(SeasonValueModel):
    def fit(self, rows, *, target_season):
        super().fit(rows, target_season=target_season)
        self.markov = OpportunityTransition().fit(rows, target_season=target_season)
        self.version = 'opportunity-markov-v1'
        return self

    def choose(self, state, values):
        if any(s >= state.season for s in self.metadata['train_seasons']):
            raise ValueError('future training')
        cat = state.chips
        if cat is None or cat.window_for(state.gw) is None:
            return None, {'reason': 'no chip window'}
        if cat.per_window != 1:
            raise ValueError('requires one chip of each kind per window')
        m = self.markov
        raw = m.support * m.scale
        visible = {int(g) for _, g in state.schedule}

        def factor(chip, gw):
            return structure_factor(chip, gw, state.schedule) if gw in visible else 1.

        # Spent chips have no current solver value; marginalize missing dimensions
        # rather than treating them as observed zero opportunities.
        observed = [i for i, c in enumerate(CHIPS) if c in values]
        if not observed:
            return None, {'reason': 'no observed opportunities'}
        vector = np.asarray([max(0., values[CHIPS[i]]) / factor(CHIPS[i], state.gw)
                             for i in observed])
        z = (vector - m.mean[observed]) / m.scale[observed]
        distances = ((m.cluster.cluster_centers_[:, observed] - z) ** 2).sum(axis=1)
        regime = int(np.argmin(distances))
        full = sum(1 << i for i, c in enumerate(CHIPS) if c in cat.chips)
        used = used_in_window(state.chips_used, cat.window_for(state.gw))
        mask = sum(1 << i for i, c in enumerate(CHIPS) if c in cat.chips and not used.get(c, 0))
        end = max(w.last_gw for w in cat.windows)

        def next_mask(gw, remaining):
            old, new = cat.window_for(gw), cat.window_for(gw + 1)
            return full if new is not None and new != old else remaining

        def expected(gw, remaining, fh, current):
            return sum(m.transition[current, j] * value(gw, remaining, fh, j) for j in range(3))

        @lru_cache(None)
        def value(gw, remaining, previous_fh, current):
            if gw > end:
                return 0.
            samples = raw[m.labels == current]
            hold = expected(gw + 1, next_mask(gw, remaining), False, current)
            choices = [np.full(len(samples), hold)]
            if cat.window_for(gw) is not None:
                for i, chip in enumerate(CHIPS):
                    if (not remaining & (1 << i) or gw in cat.unavailable_gws(chip)
                            or (chip == 'free_hit' and previous_fh)):
                        continue
                    future = expected(gw + 1, next_mask(gw, remaining & ~(1 << i)),
                                      chip == 'free_hit', current)
                    choices.append(samples[:, i] * factor(chip, gw) + future)
            return float(np.max(np.vstack(choices), axis=0).mean())

        hold = expected(state.gw + 1, next_mask(state.gw, mask), False, regime)
        actions = {'hold': hold}
        for chip in sorted(state.chips_available()):
            if chip in values and chip in CHIPS:
                i = CHIPS.index(chip)
                actions[chip] = float(values[chip]) + expected(
                    state.gw + 1, next_mask(state.gw, mask & ~(1 << i)), chip == 'free_hit', regime)
        best = max(actions, key=actions.get)
        selected = None if best == 'hold' or actions[best] <= hold + 1e-8 else best
        return selected, {'schema': 'mova-markov-season-value-v1', 'through_gw': end,
                          'q_values': actions, 'hold_value': hold, 'selected': selected,
                          'model_version': self.version, 'regime': regime,
                          'observed_dimensions': [CHIPS[i] for i in observed],
                          'bellman_states': value.cache_info().currsize,
                          'action_conditioned_transitions': False}
