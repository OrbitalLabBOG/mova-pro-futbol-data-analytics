"""Experimental joint opportunity transition model; never imported by runtime.

State is a compressed predeadline opportunity vector, not a full squad simulator.
Transitions are observed under the historical baseline policy, not causal effects
of playing a chip. All hyperparameters are fixed before opening the test fold.
"""
from __future__ import annotations

import numpy as np
from sklearn.cluster import KMeans

from mova_fpl.engine.season_value import CHIPS


def validate_rows(rows):
    keys = [(str(r['season']), int(r['gw'])) for r in rows]
    if len(keys) != len(set(keys)):
        raise ValueError('duplicate season/gameweek opportunity')
    if any(not 1 <= gw <= 38 for _, gw in keys):
        raise ValueError('invalid gameweek')
    values = []
    for r in rows:
        structure = [float(r['structure'][c]) for c in CHIPS]
        rewards = [float(r['values'][c]) for c in CHIPS]
        if not np.isfinite(structure + rewards).all() or min(structure) <= 0:
            raise ValueError('invalid opportunity vector')
        values.append(np.maximum(rewards, 0) / structure)
    return np.asarray(values, dtype=float)


class OpportunityTransition:
    """Three regimes with five pseudo-transitions toward the empirical prior."""

    version = 'opportunity-markov-v1'

    def fit(self, rows, *, target_season):
        rows = sorted(rows, key=lambda r: (r['season'], r['gw']))
        if len(rows) < 12 or any(r['season'] >= target_season for r in rows):
            raise ValueError('requires at least 12 strictly prior observations')
        raw = validate_rows(rows)
        self.mean = raw.mean(axis=0)
        self.scale = np.maximum(raw.std(axis=0), 1.)
        self.support = raw / self.scale
        self.cluster = KMeans(n_clusters=3, random_state=42, n_init=10).fit(
            (raw - self.mean) / self.scale)
        labels = self.cluster.labels_
        self.prior = np.bincount(labels, minlength=3) / len(labels)
        counts = np.zeros((3, 3))
        for i in range(len(rows) - 1):
            a, b = rows[i], rows[i + 1]
            if a['season'] == b['season'] and b['gw'] == a['gw'] + 1:
                counts[labels[i], labels[i + 1]] += 1
        if not counts.sum():
            raise ValueError('no consecutive within-season transitions')
        self.transition = (counts + 5 * self.prior) / (counts.sum(axis=1)[:, None] + 5)
        self.labels = labels
        self.metadata = {'train_seasons': sorted({r['season'] for r in rows}),
                         'target_season': target_season, 'observations': len(rows),
                         'transitions': int(counts.sum()), 'regimes': 3,
                         'prior_strength': 5, 'seed': 42,
                         'action_conditioned': False}
        return self

    def weights(self, row, *, conditioned):
        if row['season'] < self.metadata['target_season']:
            raise ValueError('inference predates training cutoff')
        raw = validate_rows([row])
        if not conditioned:
            return np.full(len(self.support), 1 / len(self.support))
        label = int(self.cluster.predict((raw - self.mean) / self.scale)[0])
        regime = self.transition[label]
        counts = np.bincount(self.labels, minlength=3)
        return regime[self.labels] / counts[self.labels]

    def score(self, current, future, *, conditioned):
        if (future['season'] != current['season']
                or future['gw'] != current['gw'] + 1):
            raise ValueError('evaluation requires consecutive same-season rows')
        weights = self.weights(current, conditioned=conditioned)
        actual = validate_rows([future])[0] / self.scale
        distances = np.linalg.norm(self.support - actual, axis=1)
        pairwise = np.linalg.norm(self.support[:, None] - self.support[None, :], axis=2)
        energy = weights @ distances - .5 * weights @ pairwise @ weights
        mean = weights @ self.support
        return {'energy_score': float(energy),
                'mean_squared_error': float(np.mean((mean - actual) ** 2))}


def evaluate_transition(train, evaluation):
    """Open one fixed chronological fold, preserve failures and all per-GW scores."""
    seasons = {r['season'] for r in evaluation}
    if len(seasons) != 1:
        raise ValueError('one test season required')
    target = next(iter(seasons))
    model = OpportunityTransition().fit(train, target_season=target)
    validate_rows(evaluation)
    evaluation = sorted(evaluation, key=lambda r: r['gw'])
    records = []
    for a, b in zip(evaluation, evaluation[1:]):
        if b['gw'] != a['gw'] + 1:
            continue
        records.append({'observed_gw': a['gw'], 'target_gw': b['gw'],
                        'stationary': model.score(a, b, conditioned=False),
                        'markov': model.score(a, b, conditioned=True)})
    if not records:
        raise ValueError('no evaluation transitions')
    means = {v: {m: float(np.mean([r[v][m] for r in records]))
                 for m in ('energy_score', 'mean_squared_error')}
             for v in ('stationary', 'markov')}
    passed = (means['markov']['energy_score'] < means['stationary']['energy_score']
              and means['markov']['mean_squared_error'] < means['stationary']['mean_squared_error'])
    return {'schema': 'mova-opportunity-transition-evaluation-v1',
            'model': model.metadata, 'evaluation_season': target,
            'pairs': len(records), 'metrics': means, 'scores': records,
            'mechanism_gate_passed': bool(passed),
            'policy_points_evaluated': False, 'promotion_authorized': False}
