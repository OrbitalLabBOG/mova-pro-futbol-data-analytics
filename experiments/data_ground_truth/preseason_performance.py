"""Retrospective GW1/prior-season reconciliation; source-code match is not identity admission."""
from __future__ import annotations

import argparse
from collections import Counter
import gzip
import json
from pathlib import Path

import pandas as pd

from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import COMPONENTS, checked, verify

FIELDS = ['minutes', 'total_points'] + [c for c in COMPONENTS if c != 'own_goals']


def totals(frame):
    result = {}
    for code, group in frame.dropna(subset=['official_player_code']).groupby('official_player_code'):
        if group['element'].nunique() != 1:
            result[int(code)] = dict(status='ambiguous_reference_code')
            continue
        values = {}
        for field in FIELDS:
            column = pd.to_numeric(group[field], errors='raise')
            known = column.dropna()
            if not known.map(lambda x: pd.notna(x) and float('-inf') < x < float('inf') and x == int(x)).all():
                raise ValueError('invalid prior integral component')
            # A partial sum is not a complete season total; all-null must not become zero.
            values[field] = None if column.isna().any() else int(column.sum())
        result[int(code)] = dict(status='unique_source_code', values=values)
    return result


def compare(row, reference):
    if reference is None:
        return dict(status='no_prior_reference_code', fields={})
    if reference['status'] != 'unique_source_code':
        return dict(status=reference['status'], fields={})
    fields = {}
    for field in FIELDS:
        cell = row['cells'].get(field, dict(status='absent', value=None))
        prior = reference['values'][field]
        if cell['status'] != 'valid':
            status = 'snapshot_'+cell['status']
        elif prior is None:
            status = 'incomplete_prior_total'
        else:
            status = 'equal' if cell['value'] == prior else 'different'
        fields[field] = dict(status=status, snapshot_value=cell['value'], prior_total=prior)
    statuses = [f['status'] for f in fields.values()]
    state = 'different' if 'different' in statuses else ('all_compared_equal' if 'equal' in statuses else 'no_comparable_fields')
    return dict(status=state, fields=fields)


def build(performance_root: Path, package: Path, out: Path):
    report_bytes = (performance_root/'report.json').read_bytes()
    report = json.loads(report_bytes)
    data = checked(performance_root/'performance.jsonl.gz', report['artifacts']['performance.jsonl.gz'])
    manifest = verify(package)
    partitions = {p['season']: p for p in manifest['partitions']}
    rows = [json.loads(line) for line in gzip.decompress(data).splitlines()]
    selected = [r for r in rows if r['gw'] == 1]
    keys = [(r['season'], r['element']) for r in selected]
    if len(set(keys)) != len(keys):
        raise ValueError('duplicate GW1 player')
    output, coverage = [], {}
    for season in sorted({r['season'] for r in selected}):
        year = int(season[:4]); prior = f'{year-1}-{year%100:02d}'
        reference = totals(pd.read_csv(package/partitions[prior]['file'])) if prior in partitions else {}
        season_rows = []
        for row in selected:
            if row['season'] != season:
                continue
            verdict = compare(row, reference.get(row['source_code']))
            season_rows.append(dict(season=season, prior_season=prior, element=row['element'],
                                    source_code=row['source_code'], source_sha256=row['source_sha256'],
                                    deadline=row['deadline'], **verdict))
        output.extend(season_rows)
        coverage[season] = dict(players=len(season_rows), prior_season=prior,
                               statuses=dict(Counter(r['status'] for r in season_rows)),
                               fields={f: dict(Counter(r['fields'][f]['status'] for r in season_rows if f in r['fields'])) for f in FIELDS})
    out.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(output, indent=2)+'\n').encode()
    (out/'comparisons.json').write_bytes(payload)
    result = dict(version='preseason-performance-v1', performance_report_sha256=digest(report_bytes),
                  reference_dataset_id=manifest['dataset_id'], implementation_sha256=digest(Path(__file__).read_bytes()),
                  rows=len(output), coverage=coverage, comparisons_sha256=digest(payload),
                  production_changed=False, training_admitted=False,
                  limitations=['retrospective_diagnostic_not_predeadline_feature_join',
                               'source_code_equality_not_independent_person_identity_proof',
                               'equal_totals_do_not_authorize_period_relabeling_of_all_fields',
                               'unmatched_codes_and_incomplete_totals_remain_unknown'])
    (out/'report.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('performance-root', 'package', 'out'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    r = build(args.performance_root, args.package, args.out)
    print(json.dumps(dict(rows=r['rows'], coverage={s:c['statuses'] for s,c in r['coverage'].items()}), indent=2))


if __name__ == '__main__':
    main()
