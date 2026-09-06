"""Audit GW1 supplemental cells against the preceding season, without imputation."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from decimal import Decimal
import gzip
import json
from pathlib import Path

from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.supplemental_components import FIELDS
from experiments.data_ground_truth.supplemental_cumulative import compare
from experiments.data_ground_truth.training_dataset import checked


def code_key(value):
    if type(value) is int and value > 0:
        return str(value)
    if isinstance(value, str) and value.isascii() and value.isdigit() and int(value) > 0:
        return str(int(value))
    raise ValueError('invalid official source code')


def references(rows):
    """Codes link seasons; reused season-local element IDs do not."""
    groups = defaultdict(list)
    seen = set()
    for row in rows:
        key = (row['season'], row['element'], row['fixture'])
        if key in seen:
            raise ValueError('duplicate reference match')
        seen.add(key)
        if row['official_player_code'] is not None:
            groups[(row['season'], code_key(row['official_player_code']))].append(row)
    result = {}
    for key, group in groups.items():
        if len({r['element'] for r in group}) != 1:
            result[key] = dict(status='ambiguous_reference_code')
            continue
        fields = {}
        for field in FIELDS:
            cells = [r['cells'][field] for r in group]
            numbers = [Decimal(str(c['value'])) for c in cells if c['status'] == 'valid']
            if any(not n.is_finite() or n < 0 for n in numbers):
                raise ValueError('invalid nonnegative reference component')
            fields[field] = dict(total=sum(numbers, Decimal(0)), count=len(cells),
                                 unknown=any(c['status'] != 'valid' for c in cells),
                                 two_decimal=all(n * 100 == (n * 100).to_integral_value() for n in numbers))
        result[key] = dict(status='unique_reference_code', fields=fields)
    return result


def compare_row(row, refs, complete):
    year = int(row['season'][:4])
    prior = f'{year - 1}-{year % 100:02d}'
    reference = refs.get((prior, code_key(row['source_code'])))
    verdicts = {}
    for field in FIELDS:
        observed = row['cells'][field]
        if observed['status'] != 'valid':
            verdict = dict(status='snapshot_' + observed['status'])
        elif prior not in complete:
            verdict = dict(status='incomplete_reference_season')
        elif reference is None:
            verdict = dict(status='no_reference_code')
        elif reference['status'] != 'unique_reference_code':
            verdict = dict(status=reference['status'])
        else:
            verdict = compare(observed, field=field, **reference['fields'][field])
        verdicts[field] = verdict
    return dict(season=row['season'], prior_season=prior, element=row['element'],
                source_code=row['source_code'], source_sha256=row['source_sha256'],
                deadline=row['deadline'], comparisons=verdicts)


def build(supplemental_root, performance_root, out):
    source_bytes = (supplemental_root / 'report.json').read_bytes()
    source = json.loads(source_bytes)
    data = checked(supplemental_root / 'components.jsonl.gz', source['artifacts']['components.jsonl.gz'])
    refs = references(json.loads(line) for line in gzip.decompress(data).splitlines())
    complete = {s for s, c in source['coverage'].items() if c['reference_rows'] > 0 and
                c['statuses'].get('linked', 0) == c['reference_rows']}
    perf_bytes = (performance_root / 'report.json').read_bytes()
    perf = json.loads(perf_bytes)
    data = checked(performance_root / 'performance.jsonl.gz', perf['artifacts']['performance.jsonl.gz'])
    selected = [r for line in gzip.decompress(data).splitlines()
                if (r := json.loads(line))['gw'] == 1]
    keys = [(r['season'], r['element']) for r in selected]
    if len(keys) != len(set(keys)):
        raise ValueError('duplicate GW1 player')
    output = [compare_row(row, refs, complete) for row in selected]
    coverage = {}
    for season in sorted({r['season'] for r in output}):
        rows = [r for r in output if r['season'] == season]
        coverage[season] = dict(rows=len(rows), fields={
            f: dict(Counter(r['comparisons'][f]['status'] for r in rows)) for f in FIELDS})
    out.mkdir(parents=True, exist_ok=True)
    payload = gzip.compress(('\n'.join(json.dumps(r, sort_keys=True) for r in output) + '\n').encode(), mtime=0)
    (out / 'comparisons.jsonl.gz').write_bytes(payload)
    result = dict(version='preseason-supplemental-v1', rows=len(output), coverage=coverage,
                  supplemental_report_sha256=digest(source_bytes), performance_report_sha256=digest(perf_bytes),
                  dataset_id=source['dataset_id'], implementation_sha256=digest(Path(__file__).read_bytes()),
                  comparisons_sha256=digest(payload), training_admitted=False, production_changed=False,
                  limitations=['retrospective_final_totals_not_predeadline_feature_values',
                               'agreement_is_not_selection_criterion_or_global_period_relabeling',
                               'source_code_match_not_independent_identity_proof',
                               'missing_reference_components_not_imputed_zero',
                               'rounding_bound_is_hypothesis_not_exact_equality',
                               'publication_witnesses_remain_separate',
                               'new_defensive_fields_do_not_have_prior_match_reference_for_2025_GW1'])
    (out / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('supplemental-root', 'performance-root', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.supplemental_root, args.performance_root, args.out), indent=2))


if __name__ == '__main__':
    main()
