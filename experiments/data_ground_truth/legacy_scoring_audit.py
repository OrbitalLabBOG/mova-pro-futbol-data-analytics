"""Arithmetic audit of archived 2015/16 FPL labels, never a label repair."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from decimal import Decimal, InvalidOperation
import gzip
import io
import json
from pathlib import Path

from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.statsbomb_player_crosswalk import archive_code
from experiments.data_ground_truth.training_dataset import checked, verify

COMPONENTS = ('minutes', 'goals_scored', 'assists', 'clean_sheets', 'goals_conceded',
              'own_goals', 'penalties_saved', 'penalties_missed', 'yellow_cards',
              'red_cards', 'saves', 'bonus')
RULE_SOURCE = 'https://eprints.lse.ac.uk/60283/1/dp1283.pdf'


def integer(value, signed=False):
    if value in ('', None):
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError('invalid integer') from exc
    if not number.is_finite() or number != number.to_integral_value() or (not signed and number < 0):
        raise ValueError('invalid integer')
    return int(number)


def score(row, position):
    if position not in (1, 2, 3, 4):
        raise ValueError('invalid historical position')
    values = {key: integer(row[key]) for key in COMPONENTS}
    if any(value is None for value in values.values()):
        return None
    v = values
    return ((2 if v['minutes'] >= 60 else int(v['minutes'] > 0))
            + (6, 6, 5, 4)[position-1] * v['goals_scored']
            + 3 * v['assists'] + (4, 4, 1, 0)[position-1] * v['clean_sheets']
            - (v['goals_conceded'] // 2 if position in (1, 2) else 0)
            + (v['saves'] // 3 if position == 1 else 0)
            + 5 * v['penalties_saved'] - 2 * v['penalties_missed']
            - 2 * v['own_goals'] - v['yellow_cards'] - 3 * v['red_cards'] + v['bonus'])


def build(package, metadata_root, comparison_root, out):
    dataset = verify(package)
    part = next(p for p in dataset['partitions'] if p['season'] == '2015-16')
    raw = checked(package / part['file'], part['sha256'])
    rows = list(csv.DictReader(io.StringIO(gzip.decompress(raw).decode())))
    manifest_bytes = (metadata_root / 'manifest.json').read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest['errors']:
        raise ValueError('metadata acquisition errors')
    metadata = {}
    for record in manifest['records']:
        if not (record['path'].startswith('PlayersInfo/') and record['path'].endswith('.json')):
            continue
        if record['repository'] != 'mvbfontes/premierleaguedatasets':
            raise ValueError('unexpected metadata source')
        player = json.loads(checked(metadata_root / 'objects' / record['sha256'], record['sha256']))
        code = archive_code(str(player['code']))
        if code is None or code in metadata:
            raise ValueError('missing or duplicate metadata identity')
        metadata[code] = dict(element=integer(player['id']), position=integer(player['element_type']),
                              source_sha256=record['sha256'])
    comparison_bytes = (comparison_root / 'report.json').read_bytes()
    comparison = json.loads(comparison_bytes)
    if comparison['dataset_id'] != dataset['dataset_id']:
        raise ValueError('comparison belongs to another GT')
    data = checked(comparison_root / 'comparisons.jsonl.gz', comparison['artifacts']['comparisons.jsonl.gz'])
    disputed = {}
    for line in gzip.decompress(data).decode().splitlines():
        row = json.loads(line)
        if any(m['status'] == 'different' for m in row['metrics'].values()):
            key = (row['fixture'], row['official_player_code'])
            if key in disputed:
                raise ValueError('duplicate comparison identity')
            disputed[key] = row['metrics']
    results = []; seen = set(); found = set()
    for row in rows:
        code = archive_code(row['official_player_code']); key = (int(row['fixture']), code)
        if key in seen:
            raise ValueError('duplicate GT identity')
        seen.add(key)
        meta = metadata.get(code)
        if meta is None or meta['element'] != integer(row['element']):
            raise ValueError('metadata identity mismatch')
        actual = integer(row['total_points'], signed=True)
        expected = score(row, meta['position'])
        status = 'unknown' if actual is None or expected is None else ('equal' if actual == expected else 'different')
        result = dict(fixture=key[0], official_player_code=code, position=meta['position'],
                      metadata_source_sha256=meta['source_sha256'], FPL_points=actual,
                      reconstructed_points=expected, status=status, positive_minutes=integer(row['minutes']) not in (None, 0))
        if key in disputed:
            found.add(key)
            replacement = dict(row)
            for metric, values in disputed[key].items():
                if integer(row[metric]) != values['FPL']:
                    raise ValueError('comparison component mismatch')
                replacement[metric] = values['provider']
            result['disputed_components'] = disputed[key]
            result['partial_provider_substitution_points'] = score(replacement, meta['position'])
        results.append(result)
    if found != set(disputed):
        raise ValueError('unmatched disputed identity')
    out.mkdir(parents=True, exist_ok=True)
    (out / 'rows.jsonl.gz').write_bytes(gzip.compress(('\n'.join(json.dumps(r, sort_keys=True) for r in results)+'\n').encode(), mtime=0))
    disputes = [r for r in results if 'disputed_components' in r]
    (out / 'disputes.json').write_text(json.dumps(disputes, indent=2)+'\n')
    report = dict(version='legacy-scoring-audit-v1', dataset_id=dataset['dataset_id'], season='2015-16',
                  partition_sha256=part['sha256'], metadata_manifest_sha256=digest(manifest_bytes),
                  comparison_report_sha256=digest(comparison_bytes), implementation_sha256=digest(Path(__file__).read_bytes()),
                  rule_source=RULE_SOURCE, rule_source_page=46, rule_source_year=2014,
                  metadata_players=len(metadata), rows=len(results),
                  arithmetic_status=dict(Counter(r['status'] for r in results)),
                  positive_arithmetic_status=dict(Counter(r['status'] for r in results if r['positive_minutes'])),
                  disputed_arithmetic_status=dict(Counter(r['status'] for r in disputes)),
                  disputed_partial_substitution_matches=sum(r['FPL_points'] == r['partial_provider_substitution_points'] for r in disputes),
                  training_admitted=False, commercial_runtime_admitted=False, raw_redistribution_admitted=False,
                  new_FPL_labels=0, production_changed=False,
                  limitations=['declared_historical_formula_not_certified_2015_official_rules',
                               'internal_arithmetic_not_independent_truth_validation',
                               'archived_clean_sheet_and_bonus_values_used_without_recalculation',
                               'partial_goal_substitution_keeps_assists_bonus_other_components_fixed_not_full_counterfactual',
                               'no_attribution_revision_cause_inferred_for_disputed_rows',
                               'research_only_StatsBomb_rights_and_temporal_limits_inherited'],
                  artifacts={name:digest((out/name).read_bytes()) for name in ('rows.jsonl.gz', 'disputes.json')})
    (out / 'report.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('package', 'metadata-root', 'comparison-root', 'out'):
        parser.add_argument('--'+name, type=Path, required=True)
    a = parser.parse_args()
    print(json.dumps(build(a.package, a.metadata_root, a.comparison_root, a.out), indent=2))


if __name__ == '__main__':
    main()
