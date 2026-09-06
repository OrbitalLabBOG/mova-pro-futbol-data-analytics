"""Audit cumulative performance cells in raw snapshots; no training/as-of admission."""
from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal, InvalidOperation
import gzip
import json
from pathlib import Path

from experiments.data_ground_truth.bootstrap_audit import decode, inspect
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked

# Explicit domains only: signed cumulative points/BPS are valid observations.
COUNTS = ('minutes', 'starts', 'goals_scored', 'assists', 'clean_sheets',
          'goals_conceded', 'saves', 'penalties_saved', 'penalties_missed',
          'yellow_cards', 'red_cards', 'bonus', 'defensive_contribution',
          'recoveries', 'tackles', 'clearances_blocks_interceptions')
SIGNED = ('total_points', 'bps')
EXPECTED = ('expected_goals', 'expected_assists', 'expected_goals_conceded',
            'expected_goal_involvements')
FIELDS = COUNTS + SIGNED + EXPECTED


def cell(element, field):
    if field not in element:
        return dict(status='absent', value=None)
    value = element[field]
    if value is None:
        return dict(status='null', value=None)
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return dict(status='invalid_type', value=None)
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return dict(status='invalid_number', value=None)
    if not number.is_finite():
        return dict(status='nonfinite', value=None)
    if field not in SIGNED and number < 0:
        return dict(status='negative', value=None)
    if field not in EXPECTED and number != number.to_integral_value():
        return dict(status='fractional_count', value=None)
    return dict(status='valid', value=str(number) if field in EXPECTED else int(number))


def build(raw_root: Path, selection_root: Path, out: Path):
    source = (raw_root / 'manifest.json').read_bytes()
    manifest = json.loads(source)
    selection_bytes = (selection_root / 'report.json').read_bytes()
    selection = json.loads(selection_bytes)
    if selection['manifest_sha256'] != digest(source) or selection['errors'] or manifest['errors']:
        raise ValueError('invalid source/selection binding')
    candidate_bytes = checked(selection_root / 'nominal_deadline_candidates.json',
                              selection['artifacts']['nominal_deadline_candidates.json'])
    candidates = json.loads(candidate_bytes)
    records = {r['path']: r for r in manifest['records']}
    keys = [(c['season'], c['gw']) for c in candidates]
    if len(set(keys)) != len(keys):
        raise ValueError('duplicate deadline')
    rows, anomalies, coverage = [], [], {}
    previous = {}
    for c in sorted(candidates, key=lambda c: (c['season'], c['gw'])):
        record = records[c['path']]
        if record['sha256'] != c['sha256']:
            raise ValueError('candidate source mismatch')
        snapshot = decode(checked(raw_root / 'objects' / c['sha256'], c['sha256']))
        _, observed = inspect(snapshot, c['path'])
        if not any(x['season'] == c['season'] and x['gw'] == c['gw'] and
                   x['deadline'] == c['deadline'] and x['source_claimed_at'] == c['source_claimed_at']
                   for x in observed):
            raise ValueError('candidate calendar mismatch')
        stats = coverage.setdefault(c['season'], dict(snapshots=0, player_rows=0,
                 managers_excluded=0, fields={f: Counter() for f in FIELDS}))
        stats['snapshots'] += 1
        seen = set()
        for e in snapshot['elements']:
            if e['element_type'] == 5:
                stats['managers_excluded'] += 1
                continue
            if e['element_type'] not in (1, 2, 3, 4) or type(e['id']) is not int or e['id'] in seen:
                raise ValueError('invalid or duplicate player identity')
            seen.add(e['id'])
            values = {f: cell(e, f) for f in FIELDS}
            context = dict(season=c['season'], gw=c['gw'], element=e['id'], source_code=e['code'],
                           source_sha256=c['sha256'], deadline=c['deadline'],
                           source_claimed_at=c['source_claimed_at'])
            row = dict(**context, cells=values, available_at=None, eligible_training=False)
            rows.append(row)
            stats['player_rows'] += 1
            if c['gw'] == 1 and values['minutes']['status'] == 'valid' and values['minutes']['value'] > 0:
                stats['gw1_players_with_nonzero_minutes'] = stats.get('gw1_players_with_nonzero_minutes', 0) + 1
            for f, v in values.items():
                stats['fields'][f][v['status']] += 1
                if v['status'] not in ('valid', 'absent', 'null'):
                    anomalies.append(dict(**context, field=f, kind=v['status'], raw_value=e[f]))
                # Diagnostic only: corrections can legitimately lower cumulative totals.
                key = (c['season'], e['id'], e['code'], f)
                old = previous.get(key)
                if v['status'] == 'valid':
                    if old is not None and Decimal(str(v['value'])) < Decimal(str(old['value'])):
                        anomalies.append(dict(**context, field=f, kind='cumulative_decrease',
                                              previous_gw=old['gw'], previous_value=old['value'],
                                              current_value=v['value']))
                    previous[key] = dict(gw=c['gw'], value=v['value'])
    out.mkdir(parents=True, exist_ok=True)
    payload = gzip.compress(('\n'.join(json.dumps(r, sort_keys=True) for r in rows)+'\n').encode(), mtime=0)
    (out/'performance.jsonl.gz').write_bytes(payload)
    anomaly_bytes = (json.dumps(anomalies, indent=2)+'\n').encode()
    (out/'anomalies.json').write_bytes(anomaly_bytes)
    report = dict(version='bootstrap-performance-v1', source_manifest_sha256=digest(source),
                  selection_report_sha256=digest(selection_bytes), candidates_sha256=digest(candidate_bytes),
                  implementation_sha256=digest(Path(__file__).read_bytes()), coverage=coverage,
                  player_rows=len(rows), anomalies=dict(Counter(a['kind'] for a in anomalies)),
                  decrease_windows=[dict(season=s, previous_gw=p, gw=g, cells=n)
                      for (s, p, g), n in sorted(Counter((a['season'], a['previous_gw'], a['gw'])
                      for a in anomalies if a['kind'] == 'cumulative_decrease').items())],
                  decrease_fields=dict(Counter(a['field'] for a in anomalies if a['kind'] == 'cumulative_decrease')),
                  artifacts={'performance.jsonl.gz': digest(payload), 'anomalies.json': digest(anomaly_bytes)},
                  training_admitted=False, production_changed=False,
                  limitations=['numeric_domains_only_not_full_semantic_validation',
                               'GW1_nonzero_totals_must_not_be_assumed_current_season',
                               'signed_points_and_BPS_can_legitimately_decrease',
                               'publication_witnesses_remain_separate_not_revalidated_here',
                               'identity_source_codes_preserved_no_cross_season_join',
                               'cumulative_decreases_are_diagnostics_not_automatic_repairs'])
    (out/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('raw-root', 'selection-root', 'out'):
        parser.add_argument('--'+name, required=True, type=Path)
    args = parser.parse_args()
    result = build(args.raw_root, args.selection_root, args.out)
    print(json.dumps({k: v for k, v in result.items() if k != 'coverage'}, indent=2))


if __name__ == '__main__':
    main()
