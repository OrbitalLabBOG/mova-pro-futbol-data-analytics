from __future__ import annotations

import copy
from dataclasses import replace

import pytest

from test_gameweek_review import _package, _official
from mova_fpl.analytics.closeout_financing import build_financing, digest, validate_financing
from mova_fpl.analytics.gameweek_review import build_decision, score_scenario, hindsight_oracle
from mova_fpl.data.private_state import validate
from mova_fpl.rules import get as get_rules


def _state(package):
    s = package['selected']
    return {'schema': 'mova-fpl-private-team-state-v1',
            'observed_at': '2026-08-21T16:00:00Z', 'team_id': package['entry_id'],
            'event': {'id': package['gw'], 'deadline_time': package['deadline_at']},
            'picks_last_updated': None,
            'picks': [{'element': r['element'], 'element_type': {'GKP': 1, 'DEF': 2, 'MID': 3, 'FWD': 4}[r['position']],
                       'position': i, 'multiplier': 2 if r['element'] == s['captain'] else int(i <= 11),
                       'is_captain': r['element'] == s['captain'],
                       'is_vice_captain': r['element'] == s['vice_captain'],
                       'purchase_price': round(r['price'] * 10), 'selling_price': round(r['price'] * 10)}
                      for i, r in enumerate(s['players'], 1)],
            'transfers': {'bank': 0, 'value': 1100, 'limit': 1, 'made': 0, 'cost': 0, 'status': 'cost'},
            'chips': []}


def _proof(state):
    return {'artifact_path': '/sealed/private', 'manifest_sha256': 'a' * 64,
            'fingerprint': validate(state)[1]['fingerprint']}


def _certificate(package, decision, before=None, after=None):
    before = before or _state(package)
    return build_financing(before=before, before_source=_proof(before), decision=decision,
                           market_prices={p['element']: p['purchase_price'] + 10 for p in before['picks']} | {999: 70},
                           price_source={'batch_id': 'approved', 'input_artifact_id': 'sealed',
                                         'cutoff_at': '2026-08-21T16:00:00Z'},
                           deadline_at=package['deadline_at'], after=after,
                           after_source=_proof(after) if after else None)


@pytest.mark.parametrize('chip,points', [(None, 50), ('bench_boost', 75), ('triple_captain', 52)])
def test_chip_attribution_and_expectation_reconcile(chip, points):
    _, p = _package(); s = copy.deepcopy(p['selected']); s['chip'] = chip
    d = build_decision(s, p['season'], p['gw']); rules = get_rules(p['season']).SQUAD
    score, rows = score_scenario(s, d, _official(p), rules)
    assert score['points_before_hits'] == points == sum(r['effective_points'] for r in rows)
    expected = sum(r['expected_points'] for r in s['players'] if chip == 'bench_boost' or r['role'] == 'starter')
    expected += next(r['expected_points'] for r in s['players'] if r['element'] == d.captain) * (2 if chip == 'triple_captain' else 1)
    assert score['expected_total_recomputed'] == round(expected, 2)
    assert hindsight_oracle(s, _official(p), rules) >= score['points']


@pytest.mark.parametrize('chip', [None, 'bench_boost', 'triple_captain'])
def test_absent_captain_vice_autosubs_and_hits_reconcile(chip):
    _, p = _package(); s = copy.deepcopy(p['selected']); s.update(chip=chip, hits=1)
    d = build_decision(s, p['season'], 1); official = _official(p)
    for r in official['live']:
        if r['element'] == d.captain: r.update(minutes=0, total_points=0)
    score, rows = score_scenario(s, d, official, get_rules(p['season']).SQUAD)
    assert score['effective_captain'] == d.vice_captain
    assert score['points'] == sum(r['effective_points'] for r in rows) - 4
    vice = next(r for r in rows if r['element'] == d.vice_captain)
    assert vice['multiplier'] == (3 if chip == 'triple_captain' else 2)


def test_missing_probabilities_and_absent_live_rows_do_not_break_settlement():
    _, p = _package(); s = copy.deepcopy(p['selected'])
    for r in s['players']: r['p60'] = None
    official = _official(p); absent = s['bench_order'][0]
    official['live'] = [r for r in official['live'] if r['element'] != absent]
    score, rows = score_scenario(s, build_decision(s, p['season'], 1), official, get_rules(p['season']).SQUAD)
    assert score['p60_brier_15'] is None and score['p60_observations'] == 0
    assert score['p60_unavailable_reason'] == 'probabilities_missing'
    assert sum(r['effective_points'] for r in rows) == score['points_before_hits']


def test_appreciated_owned_roster_is_valid_only_with_financing_evidence():
    _, p = _package(); s = copy.deepcopy(p['selected']); d = build_decision(s, p['season'], 1)
    for r in s['players']: r['price'] += 1
    with pytest.raises(ValueError, match='BUDGET'):
        score_scenario(s, d, _official(p), get_rules(p['season']).SQUAD)
    s['financing'] = _certificate(p, d, after=_state(p))
    score, _ = score_scenario(s, d, _official(p), get_rules(p['season']).SQUAD)
    assert score['points'] == 50


@pytest.mark.parametrize('chip', [None, 'wildcard', 'free_hit'])
def test_financed_transfer_and_special_chip_contracts(chip):
    _, p = _package(); before = _state(p); old = before['picks'][-1]['element']
    before['transfers']['bank'] = 100
    d = build_decision(p['selected'], p['season'], 1)
    bank = (100 + before['picks'][-1]['selling_price'] - 70) / 10
    d = replace(d, squad_15=tuple(999 if e == old else e for e in d.squad_15),
                bench_order=tuple(999 if e == old else e for e in d.bench_order),
                transfers_in=(999,), transfers_out=(old,), chip=chip, bank_after=bank)
    after = copy.deepcopy(before); after['observed_at'] = '2026-08-21T16:30:00Z'
    after['transfers']['bank'] = round(bank * 10)
    after['picks'][-1].update(element=999, purchase_price=70, selling_price=70)
    c = _certificate(p, d, before, after)
    v = validate_financing(c, d)
    assert v['bank_after_tenths'] == round(bank * 10)
    assert (v['reversion'] is not None) == (chip == 'free_hit')
    if chip == 'free_hit': assert v['reversion']['status'] == 'pending_next_gameweek'


@pytest.mark.parametrize('tamper', ['bank', 'sale', 'price', 'purchase', 'time', 'reversion', 'seal'])
def test_financing_rejects_false_or_incompatible_evidence(tamper):
    _, p = _package(); d = build_decision(p['selected'], p['season'], 1)
    c = _certificate(p, d, after=_state(p))
    if tamper == 'bank': c['bank_after_tenths'] = 10
    elif tamper == 'sale': d = replace(d, transfers_out=(999,))
    elif tamper == 'price': c['market_prices_tenths']['109'] = -10
    elif tamper == 'purchase': c['after']['picks'][0]['purchase_price'] += 1; c['after_source'] = _proof(c['after'])
    elif tamper == 'time': c['price_source']['cutoff_at'] = '2026-08-30T00:00:00Z'
    elif tamper == 'reversion': c['reversion'] = {'status': 'proven'}
    if tamper != 'seal': c['content_sha256'] = digest({k: v for k, v in c.items() if k != 'content_sha256'})
    else: c['bank_after_tenths'] = 100
    with pytest.raises(ValueError): validate_financing(c, d)


def test_manual_legacy_closeout_is_not_counted_as_financed_autonomous_evidence(tmp_path):
    from mova_fpl.ops.db import OpsDB
    db = OpsDB(tmp_path/'ops.db', enforce_version=False); db.migrate()
    cycle = db.upsert_cycle('2026-27', 1, '2026-08-21T17:30:00Z', phase='settlement')
    job, _ = db.start_job('gameweek_review', 'autonomous-closeout:2026-27:gw01:v1', 'corr', cycle_id=cycle)
    db.finish_job(job, 'completed', metrics={'closeout_contract': 'mova-fpl-autonomous-closeout-v1'})
    summary = db.autonomous_closeout_summary('2026-27')
    assert summary['observed_closeouts'] == 0 and summary['latest'] is None
    job, _ = db.start_job('gameweek_review', 'autonomous-closeout:2026-27:gw01:v2', 'corr2', cycle_id=cycle)
    db.finish_job(job, 'completed', metrics={'closeout_contract': 'mova-fpl-autonomous-closeout-v2'})
    summary = db.autonomous_closeout_summary('2026-27')
    assert summary['observed_closeouts'] == 1
    assert summary['autonomy_promoted'] is False
