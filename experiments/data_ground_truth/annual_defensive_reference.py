"""Preserve annual defensive observations separately from per-match labels."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import gzip
import io
import json
from pathlib import Path

from experiments.data_ground_truth.bootstrap_performance import cell
from experiments.data_ground_truth.preseason_supplemental import code_key
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked

FIELDS = ('defensive_contribution', 'recoveries', 'tackles', 'clearances_blocks_interceptions')
SEASON = '2024/25'


def consensus(observations):
    """Keep conflicting versions and absent values; never majority-vote a label."""
    result = {}
    for field in FIELDS:
        states = Counter(o['cells'][field]['status'] for o in observations)
        values = sorted({o['cells'][field]['value'] for o in observations
                         if o['cells'][field]['status'] == 'valid'})
        status = 'conflict' if len(values) > 1 else 'observed_value' if values else 'unknown'
        result[field] = dict(status=status, value=values[0] if len(values) == 1 else None,
                             observed_values=values, source_states=dict(states))
    return result


def compare_cells(snapshot, annual):
    results = {}
    for field in FIELDS:
        observed = snapshot['cells'][field]
        if observed['status'] != 'valid':
            results[field] = dict(status='snapshot_' + observed['status'])
        elif annual is None:
            results[field] = dict(status='no_annual_reference')
        elif annual[field]['status'] != 'observed_value':
            results[field] = dict(status='annual_' + annual[field]['status'])
        else:
            value = annual[field]['value']
            results[field] = dict(status='equal' if value == observed['value'] else 'different',
                                   snapshot_value=observed['value'], annual_value=value)
    return results


def build(raw_roots, performance_root, out):
    observations = []
    manifests = []
    seen = set()
    scanned_files = 0
    for root in raw_roots:
        source = (root / 'manifest.json').read_bytes()
        manifest = json.loads(source)
        if manifest['errors'] or len(manifest['records']) != manifest['expected_files']:
            raise ValueError('incomplete acquisition manifest')
        source_sha = digest(source)
        if source_sha in manifests:
            raise ValueError('duplicate acquisition manifest')
        manifests.append(source_sha)
        for record in manifest['records']:
            key = (source_sha, record['path'])
            if key in seen:
                raise ValueError('duplicate source path')
            seen.add(key)
            body = checked(root / 'objects' / record['sha256'], record['sha256'])
            if len(body) != record['bytes']:
                raise ValueError('source size mismatch')
            scanned_files += 1
            for row_number, row in enumerate(csv.DictReader(io.StringIO(body.decode('utf-8-sig'))), start=2):
                if row.get('season_name') != SEASON:
                    continue
                cells = {f: (dict(status='empty', value=None) if row.get(f) == '' else cell(row, f)) for f in FIELDS}
                observations.append(dict(season=SEASON, source_code=code_key(row['element_code']),
                    source_path=record['path'], source_sha256=record['sha256'],
                    manifest_sha256=source_sha, csv_row=row_number, cells=cells,
                    available_at=None, eligible_predeadline=False))
    groups = defaultdict(list)
    for row in observations:
        groups[row['source_code']].append(row)
    annual = {code: consensus(group) for code, group in sorted(groups.items())}
    reference_rows = [dict(season=SEASON, source_code=code, cells=cells,
                          source_observations=len(groups[code]), training_admitted=False)
                      for code, cells in annual.items()]
    perf_bytes = (performance_root / 'report.json').read_bytes()
    perf = json.loads(perf_bytes)
    body = checked(performance_root / 'performance.jsonl.gz', perf['artifacts']['performance.jsonl.gz'])
    comparisons = []
    snapshot_keys = set()
    for line in gzip.decompress(body).splitlines():
        row = json.loads(line)
        if row['season'] != '2025-26' or row['gw'] != 1:
            continue
        if row['element'] in snapshot_keys:
            raise ValueError('duplicate GW1 player')
        snapshot_keys.add(row['element'])
        comparisons.append(dict(season=row['season'], gw=1, element=row['element'],
            source_code=code_key(row['source_code']), source_sha256=row['source_sha256'],
            comparisons=compare_cells(row, annual.get(code_key(row['source_code'])))))
    out.mkdir(parents=True, exist_ok=True)
    artifacts = {}
    for name, rows in [('observations', observations), ('annual-reference', reference_rows), ('comparisons', comparisons)]:
        payload = gzip.compress(('\n'.join(json.dumps(r, sort_keys=True) for r in rows) + '\n').encode(), mtime=0)
        filename = name + '.jsonl.gz'
        (out / filename).write_bytes(payload)
        artifacts[filename] = digest(payload)
    result = dict(version='annual-defensive-reference-v1', season=SEASON,
        source_manifest_sha256=manifests, scanned_files=scanned_files,
        performance_report_sha256=digest(perf_bytes), implementation_sha256=digest(Path(__file__).read_bytes()),
        source_observations=len(observations), unique_player_seasons=len(annual),
        observed_fields={f: dict(Counter(o['cells'][f]['status'] for o in observations)) for f in FIELDS},
        consensus_fields={f: dict(Counter(r[f]['status'] for r in annual.values())) for f in FIELDS},
        unique_positive_values={f: sum(r[f]['status'] == 'observed_value' and r[f]['value'] > 0 for r in annual.values()) for f in FIELDS},
        snapshot_rows=len(comparisons), comparisons={f: dict(Counter(r['comparisons'][f]['status'] for r in comparisons)) for f in FIELDS},
        artifacts=artifacts, training_admitted=False, production_changed=False,
        limitations=['annual_totals_not_player_match_labels_or_new_complete_season',
                     'repeated_versions_of_one_upstream_not_independent_sources',
                     'explicit_zero_components_do_not_establish_complete_sporting_measurement',
                     'positive_contribution_with_zero_components_is_not_reconstructible',
                     'retrospective_acquisition_not_predeadline_availability',
                     'agreement_does_not_authorize_overwriting_snapshot_or_training_selection',
                     'no_retrospective_award_of_new_rules_points',
                     'source_code_match_not_independent_person_identity_proof'])
    (out / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw-root', type=Path, action='append', required=True)
    parser.add_argument('--performance-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.raw_root, args.performance_root, args.out), indent=2))


if __name__ == '__main__':
    main()
