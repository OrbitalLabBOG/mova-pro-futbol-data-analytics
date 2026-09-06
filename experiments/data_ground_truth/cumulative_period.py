"""Compare raw cumulative cells with two retrospective label cutoffs."""
from __future__ import annotations

import argparse
from collections import Counter
import gzip
import json
from pathlib import Path

import pandas as pd

from experiments.data_ground_truth.preseason_performance import compare, totals
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked, verify


def references(frame, gw, deadline):
    weeks = pd.to_numeric(frame['gw'], errors='raise')
    times = pd.to_datetime(frame['event_time_utc'], utc=True, errors='raise')
    cutoff = pd.Timestamp(deadline)
    if cutoff.tzinfo is None:
        raise ValueError('deadline must have timezone')
    nominal = totals(frame.loc[weeks < gw])
    temporal = totals(frame.loc[times < cutoff])
    # Unknown event times can hide contributions; do not call a partial sum complete.
    for code in frame.loc[times.isna(), 'official_player_code'].dropna():
        temporal[int(code)] = dict(status='unknown_event_time')
    return nominal, temporal, dict(missing_event_times=int(times.isna().sum()),
                                   differing_row_membership=int(((weeks < gw) != (times < cutoff)).sum()),
                                   kickoffs_within_four_hours=int(((times < cutoff) &
                                       (times >= cutoff - pd.Timedelta(hours=4))).sum()))


def build(performance_root, package, out):
    report_bytes = (performance_root / 'report.json').read_bytes()
    report = json.loads(report_bytes)
    data = checked(performance_root / 'performance.jsonl.gz', report['artifacts']['performance.jsonl.gz'])
    manifest = verify(package)
    rows = [json.loads(line) for line in gzip.decompress(data).splitlines()]
    keys = [(r['season'], r['gw'], r['element']) for r in rows]
    if len(keys) != len(set(keys)):
        raise ValueError('duplicate snapshot player')
    partitions = {p['season']: p for p in manifest['partitions']}
    coverage, output = {}, []
    for season in sorted({r['season'] for r in rows}):
        if season not in partitions:
            coverage[season] = dict(status='no_reference_season')
            continue
        frame = pd.read_csv(package / partitions[season]['file'])
        season_rows = [r for r in rows if r['season'] == season and r['gw'] > 1]
        windows = []
        for gw in sorted({r['gw'] for r in season_rows}):
            selected = [r for r in season_rows if r['gw'] == gw]
            deadlines = {r['deadline'] for r in selected}
            if len(deadlines) != 1:
                raise ValueError('inconsistent deadline')
            deadline = deadlines.pop()
            nominal, temporal, diagnostics = references(frame, gw, deadline)
            states = {'nominal_gw': Counter(), 'kickoff_before_deadline': Counter()}
            field_states = {'nominal_gw': Counter(), 'kickoff_before_deadline': Counter()}
            changes = Counter()
            for row in selected:
                result = dict(season=season, gw=gw, element=row['element'], source_code=row['source_code'],
                              source_sha256=row['source_sha256'], deadline=deadline, comparisons={})
                for mode, refs in [('nominal_gw', nominal), ('kickoff_before_deadline', temporal)]:
                    verdict = compare(row, refs.get(row['source_code']))
                    status = verdict['status'].replace('no_prior_reference_code', 'no_reference_code')
                    states[mode][status] += 1
                    field_states[mode].update(c['status'] for c in verdict['fields'].values())
                    result['comparisons'][mode] = dict(status=status, differences={
                        f: dict(snapshot_value=c['snapshot_value'], final_reference_total=c['prior_total'])
                        for f, c in verdict['fields'].items() if c['status'] == 'different'})
                changes[(result['comparisons']['nominal_gw']['status'],
                         result['comparisons']['kickoff_before_deadline']['status'])] += 1
                output.append(result)
            windows.append(dict(gw=gw, deadline=deadline, rows=len(selected), diagnostics=diagnostics,
                                statuses={m: dict(c) for m, c in states.items()},
                                cells={m: dict(c) for m, c in field_states.items()},
                                transitions=[dict(nominal=a, temporal=b, rows=n) for (a,b),n in sorted(changes.items())]))
        coverage[season] = dict(status='compared', windows=windows)
    out.mkdir(parents=True, exist_ok=True)
    payload = gzip.compress(('\n'.join(json.dumps(r, sort_keys=True) for r in output)+'\n').encode(), mtime=0)
    (out/'comparisons.jsonl.gz').write_bytes(payload)
    result = dict(version='cumulative-period-v1', dataset_id=manifest['dataset_id'],
                  performance_report_sha256=digest(report_bytes), implementation_sha256=digest(Path(__file__).read_bytes()),
                  rows=len(output), coverage=coverage, comparisons_sha256=digest(payload),
                  training_admitted=False, production_changed=False,
                  limitations=['retrospective_final_labels_not_historical_versions',
                               'kickoff_before_deadline_does_not_prove_match_finished_or_data_published',
                               'snapshot_can_predate_deadline_and_latest_matches',
                               'unknown_event_times_invalidate_code_temporal_total',
                               'missing_reference_rows_not_imputed_to_zero',
                               'GW1_excluded_due_to_prior_season_semantics',
                               'publication_and_identity_witnesses_not_revalidated'])
    (out/'report.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('performance-root', 'package', 'out'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    result = build(args.performance_root, args.package, args.out)
    print(json.dumps(dict(rows=result['rows'], seasons=list(result['coverage']))))


if __name__ == '__main__':
    main()
