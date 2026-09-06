"""Retrospectively compare GW2 bootstrap totals with finalized GW1 labels."""
from __future__ import annotations

import argparse
from collections import Counter
import gzip
import json
from pathlib import Path

import pandas as pd

from experiments.data_ground_truth.preseason_performance import FIELDS, compare, totals
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked, verify


def reference(frame):
    """Absent GW1 rows remain unknown, never synthesized as zero appearances."""
    return totals(frame.loc[pd.to_numeric(frame['gw'], errors='raise') == 1])


def build(performance_root, package, out):
    report_bytes = (performance_root / 'report.json').read_bytes()
    report = json.loads(report_bytes)
    payload = checked(performance_root / 'performance.jsonl.gz',
                      report['artifacts']['performance.jsonl.gz'])
    manifest = verify(package)
    partitions = {p['season']: p for p in manifest['partitions']}
    rows = [json.loads(line) for line in gzip.decompress(payload).splitlines()]
    selected = [r for r in rows if r['gw'] == 2]
    keys = [(r['season'], r['element']) for r in selected]
    if len(keys) != len(set(keys)):
        raise ValueError('duplicate GW2 player')
    comparisons, coverage = [], {}
    for season in sorted({r['season'] for r in selected}):
        refs = reference(pd.read_csv(package / partitions[season]['file'])) if season in partitions else {}
        season_rows = []
        for row in selected:
            if row['season'] != season:
                continue
            verdict = compare(row, refs.get(row['source_code']))
            if verdict['status'] == 'no_prior_reference_code':
                verdict['status'] = 'no_gw1_reference_code'
            # Shared comparator's prior_total means the explicitly selected GW1 sum here.
            for cell in verdict['fields'].values():
                cell['gw1_final_total'] = cell.pop('prior_total')
            season_rows.append(dict(season=season, element=row['element'],
                                    source_code=row['source_code'], source_sha256=row['source_sha256'],
                                    deadline=row['deadline'], **verdict))
        comparisons.extend(season_rows)
        coverage[season] = dict(rows=len(season_rows), statuses=dict(Counter(r['status'] for r in season_rows)),
                               fields={f: dict(Counter(r['fields'][f]['status'] for r in season_rows
                                                       if f in r['fields'])) for f in FIELDS})
    out.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(comparisons, indent=2) + '\n').encode()
    (out / 'comparisons.json').write_bytes(data)
    result = dict(version='gw2-period-v1', performance_report_sha256=digest(report_bytes),
                  dataset_id=manifest['dataset_id'], implementation_sha256=digest(Path(__file__).read_bytes()),
                  rows=len(comparisons), coverage=coverage, comparisons_sha256=digest(data),
                  training_admitted=False, production_changed=False,
                  limitations=['finalized_GW1_is_retrospective_reference_not_as_of_truth',
                               'agreement_does_not_admit_other_fields_or_other_gameweeks',
                               'missing_player_rows_not_imputed_to_zero',
                               'publication_witnesses_not_revalidated',
                               'source_code_match_not_independent_identity_proof'])
    (out / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('performance-root', 'package', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    result = build(args.performance_root, args.package, args.out)
    print(json.dumps({s: c['statuses'] for s, c in result['coverage'].items()}, indent=2))


if __name__ == '__main__':
    main()
