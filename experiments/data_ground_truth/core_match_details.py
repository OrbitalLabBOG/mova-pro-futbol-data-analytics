"""Acquire and measure archived match detail without admitting training features."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import csv
import gzip
import io
import json
from pathlib import Path

from experiments.data_ground_truth.preseason_supplemental import code_key
from experiments.data_ground_truth.raw import capture, digest
from experiments.data_ground_truth.training_dataset import checked

REPOSITORY = 'olbauday/FPL-Core-Insights'
REVISION = 'ce03f31b4032f3f89a1aa460ddc8a709ddeb56b6'
TABLES = ('average_positions', 'incidents', 'lineups', 'match_enrichment',
          'momentum', 'player_match_enrichment', 'shots', 'xg_by_minute')
KEYS = {'average_positions': ('match_id', 'team_side', 'player_id'),
        'incidents': ('match_id', 'incident_index'),
        'lineups': ('match_id', 'team_side', 'player_id'),
        'match_enrichment': ('match_id',), 'momentum': ('match_id', 'minute'),
        'player_match_enrichment': ('match_id', 'player_id'),
        'shots': ('match_id', 'shot_index'), 'xg_by_minute': ('match_id', 'minute')}


def paths():
    return [f'data/2025-2026/By Tournament/Premier League/GW{gw}/{table}.csv'
            for gw in range(1, 39) for table in TABLES]


def acquire(root):
    # Existing capture verifies cached objects and atomically publishes downloads.
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(lambda path: capture(root, REPOSITORY, REVISION, path), paths()))
    manifest = dict(version='core-match-details-raw-v1', repository=REPOSITORY,
                    revision=REVISION, tables=list(TABLES), expected_paths=paths(),
                    records=sorted(records, key=lambda r: r['path']), errors=[])
    (root / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


def key_status(row, fields):
    values = tuple(row.get(field) for field in fields)
    return None if any(value is None or value == '' for value in values) else values


def field_coverage(rows):
    fields = sorted({field for row in rows for field in row})
    return {field: dict(Counter('absent' if field not in row else
                'empty' if row[field] in ('', None) else 'populated' for row in rows))
            for field in fields}


def build(root, calibration_root, out):
    manifest_bytes = (root / 'manifest.json').read_bytes()
    manifest = json.loads(manifest_bytes)
    actual = [r['path'] for r in manifest['records']]
    if manifest['errors'] or len(actual) != len(paths()) or set(actual) != set(paths()):
        raise ValueError('incomplete or duplicate acquisition scope')
    if manifest['repository'] != REPOSITORY or manifest['revision'] != REVISION:
        raise ValueError('unexpected source revision')
    parent_bytes = (calibration_root / 'report.json').read_bytes()
    parent = json.loads(parent_bytes)
    body = checked(calibration_root / 'comparisons.jsonl.gz', parent['artifacts']['comparisons.jsonl.gz'])
    reference = [json.loads(line) for line in gzip.decompress(body).splitlines()]
    matches = {}; players = {}; played = set()
    for row in reference:
        match = row['source_match_id']; player = code_key(row['player_id'])
        if match in matches and matches[match] != row['fixture']:
            raise ValueError('ambiguous reference fixture')
        if player in players and players[player] != row['source_code']:
            raise ValueError('ambiguous reference player')
        matches[match] = row['fixture']; players[player] = row['source_code']
        if row['FPL_minutes'] is not None and row['FPL_minutes'] > 0:
            played.add((match, player))
    tables = defaultdict(list); normalized = []; issues = []; source_bytes = 0
    for record in sorted(manifest['records'], key=lambda r: r['path']):
        if record['repository'] != REPOSITORY or record['revision'] != REVISION:
            raise ValueError('record source mismatch')
        raw = checked(root / 'objects' / record['sha256'], record['sha256'])
        if len(raw) != record['bytes']:
            raise ValueError('source size mismatch')
        source_bytes += len(raw)
        table = Path(record['path']).stem
        reader = csv.DictReader(io.StringIO(raw.decode()))
        if reader.fieldnames is None or len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError('absent or duplicate CSV header')
        for number, row in enumerate(reader, start=2):
            if None in row:
                raise ValueError('malformed CSV row')
            tables[table].append(row)
            normalized.append(dict(table=table, source_sha256=record['sha256'], path=record['path'],
                csv_row=number, fixture=matches.get(row.get('match_id')), raw=row,
                available_at=None, eligible_predeadline=False))
    reports = {}
    for table in TABLES:
        rows = tables[table]; seen = Counter(); invalid_keys = 0
        match_ids = {r.get('match_id') for r in rows}; ids = Counter(); pairs = set()
        for row in rows:
            key = key_status(row, KEYS[table])
            if key is None: invalid_keys += 1
            else: seen[key] += 1
            for field in ('player_id', 'secondary_player_id', 'assist_player_id'):
                if field not in row: continue
                raw_id = row[field]
                if raw_id in ('', None): ids[field + ':empty'] += 1; continue
                player = code_key(raw_id)
                ids[field + (':linked_reference' if player in players else ':outside_reference')] += 1
                if field == 'player_id': pairs.add((row['match_id'], player))
        duplicates = sum(count - 1 for count in seen.values() if count > 1)
        missing = sorted(set(matches) - match_ids)
        report = dict(rows=len(rows), matches=len(match_ids), reference_matches=len(matches),
            covered_reference_matches=len(set(matches) & match_ids), missing_reference_matches=missing,
            outside_reference_matches=sorted(match_ids - set(matches)), invalid_keys=invalid_keys,
            duplicate_key_excess_rows=duplicates, identity_fields=dict(ids), fields=field_coverage(rows))
        if table in ('lineups', 'average_positions', 'player_match_enrichment'):
            report['positive_FPL_appearances'] = dict(reference=len(played), covered=len(played & pairs),
                missing=len(played - pairs), outside_positive_reference=len(pairs - played))
            issues.extend(dict(table=table, kind='missing_positive_appearance', match_id=m, player_id=p)
                          for m, p in sorted(played - pairs))
        if table == 'lineups':
            starters = Counter((r['match_id'], r['team_side']) for r in rows if r['is_starting'] == 'True')
            report['starting_eleven_violations'] = [dict(match_id=m, side=s, count=starters[(m,s)])
                for m in sorted(matches) for s in ('home', 'away') if starters[(m,s)] != 11]
            report['starting_flags'] = dict(Counter(r['is_starting'] for r in rows))
            report['lineup_status'] = dict(Counter(r['lineup_status'] for r in rows))
        reports[table] = report
    out.mkdir(parents=True, exist_ok=True)
    (out / 'observations.jsonl.gz').write_bytes(gzip.compress(
        ('\n'.join(json.dumps(r, sort_keys=True) for r in normalized) + '\n').encode(), mtime=0))
    (out / 'coverage-issues.json').write_text(json.dumps(issues, indent=2) + '\n')
    result = dict(version='core-match-details-v1', raw_manifest_sha256=digest(manifest_bytes),
        calibration_report_sha256=digest(parent_bytes), implementation_sha256=digest(Path(__file__).read_bytes()),
        source_files=len(actual), source_bytes=source_bytes, tables=reports,
        dataset_id=parent['dataset_id'], new_FPL_labels=0, training_admitted=False, production_changed=False,
        limitations=['coverage_does_not_prove_accuracy_or_independent_source',
            'reference_player_mapping_limited_to_G62_comparison_population',
            'empty_values_not_zero_imputed', 'attacking_shots_blocked_not_defender_blocks',
            'confirmed_lineup_label_does_not_prove_predeadline_availability',
            'populated_cells_not_full_semantic_or_numeric_validation'],
        artifacts={name: digest((out / name).read_bytes()) for name in ('observations.jsonl.gz', 'coverage-issues.json')})
    (out / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--calibration-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--acquire', action='store_true')
    args = parser.parse_args()
    if args.acquire: acquire(args.root)
    print(json.dumps(build(args.root, args.calibration_root, args.out), indent=2))


if __name__ == '__main__':
    main()
