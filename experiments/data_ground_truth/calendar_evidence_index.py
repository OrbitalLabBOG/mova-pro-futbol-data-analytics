"""Index independently reproduced calendar evidence without conflating source clocks."""
from __future__ import annotations

import argparse
from collections import Counter
import gzip
import json
from pathlib import Path

from experiments.data_ground_truth import calendar_extension_selection as external
from experiments.data_ground_truth import collector_public_audit as collector
from experiments.data_ground_truth.bootstrap_time import aware
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked


def combine(targets, external_rows, own_rows):
    universe = {}
    for target in targets:
        key = (target['season'], target['gw'])
        if key in universe:
            raise ValueError('duplicate target')
        universe[key] = target['deadline']
    rows = []
    seen = set()
    for origin, source in [('external_publication', external_rows),
                           ('own_collector_ingestion_ledger', own_rows)]:
        for item in source:
            key = (item['season'], item['gw'])
            if key not in universe or aware(item['deadline']) != aware(universe[key]):
                raise ValueError('unknown or conflicting deadline')
            if (origin, key) in seen:
                raise ValueError('duplicate source deadline')
            seen.add((origin, key))
            own = origin == 'own_collector_ingestion_ledger'
            if own and (item['evidence_origin'] != origin or item['eligible_training'] is not False):
                raise ValueError('collector evidence contract mismatch')
            if not own and item['proof']['eligible_predeadline'] is not True:
                raise ValueError('external publication not proven')
            clock = item['observed_at'] if own else item['source_committer_at']
            if not aware(clock) <= aware(item['available_at']) < aware(item['deadline']):
                raise ValueError('invalid availability interval')
            age = (aware(item['deadline']) - aware(clock)).total_seconds()/3600
            rows.append(dict(season=key[0], gw=key[1], deadline=universe[key],
                             evidence_origin=origin, available_at=item['available_at'],
                             source_clock=clock,
                             source_clock_kind='collection_started_at' if own else 'git_committer_at',
                             source_clock_age_hours=age,
                             normalized_sha256=item['normalized_fixtures_sha256'] if own else item['normalized_sha256'],
                             object_root='collector-public-audit-v2' if own else item['object_root'],
                             evidence=item, eligible_training=False))
    coverage = {}
    covered = {(r['season'], r['gw']) for r in rows}
    for season in sorted({s for s, _ in universe}):
        subset = [r for r in rows if r['season'] == season]
        coverage[season] = dict(expected=sum(s == season for s, _ in universe),
                               covered=len({r['gw'] for r in subset}),
                               by_origin=dict(Counter(r['evidence_origin'] for r in subset)))
    # Report clocks separately: commit age is not observed API capture freshness.
    freshness = {}
    for origin in ('external_publication', 'own_collector_ingestion_ledger'):
        ages = [r['source_clock_age_hours'] for r in rows if r['evidence_origin'] == origin]
        freshness[origin] = dict(observations=len(ages), within48h=sum(a <= 48 for a in ages),
                                maximum_age_hours=max(ages) if ages else None)
    return sorted(rows, key=lambda r:(r['season'], r['gw'], r['evidence_origin'])), dict(
        expected_deadlines=len(universe), covered_deadlines=len(covered),
        evidence_records=len(rows), coverage=coverage, source_clock_age=freshness,
        missing=[dict(season=s, gw=g, deadline=universe[(s,g)]) for s,g in sorted(universe.keys()-covered)])


def build(base: Path, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    external_root = base/'calendar-extension-selection-v1'
    own_root = base/'collector-public-audit-v2'
    external.build(base, [base/'calendar-publication-extension-v1',
                         base/'calendar-descendant-publication-v2'], out/'external_revalidated')
    collector.build(base, base/'raw-collector-public-v2',
                    base/'raw-production-discovery-v1/collector-ledger-parsed.json', out/'collector_revalidated')
    for original, reproduced, files in [
        (external_root, out/'external_revalidated', ('report.json', 'selected_calendars.json')),
        (own_root, out/'collector_revalidated', ('report.json', 'captures.json', 'selected_deadlines.json')),
    ]:
        for name in files:
            if (original/name).read_bytes() != (reproduced/name).read_bytes():
                raise ValueError('parent reproduction mismatch: '+name)
    er_bytes = (external_root/'report.json').read_bytes(); er = json.loads(er_bytes)
    cr_bytes = (own_root/'report.json').read_bytes(); cr = json.loads(cr_bytes)
    tr_bytes = (base/'publication-selection-v1/report.json').read_bytes(); tr = json.loads(tr_bytes)
    targets = json.loads(checked(base/'publication-selection-v1/nominal_deadline_candidates.json',
                                tr['artifacts']['nominal_deadline_candidates.json']))
    erows = json.loads(checked(external_root/'selected_calendars.json', er['selected_sha256']))
    crows = json.loads(checked(own_root/'selected_deadlines.json', cr['artifacts']['selected_deadlines.json']))
    rows, summary = combine(targets, erows, crows)
    for row in rows:
        fixtures = json.loads(gzip.decompress(checked(base/row['object_root']/'objects'/row['normalized_sha256'], row['normalized_sha256'])))
        if len(fixtures) != 380 or len({f['id'] for f in fixtures}) != 380:
            raise ValueError('incomplete calendar')
    payload = (json.dumps(rows, indent=2)+'\n').encode()
    (out/'calendar_evidence.json').write_bytes(payload)
    report = dict(version='calendar-evidence-index-v1', **summary,
                  external_parent_sha256=digest(er_bytes), collector_parent_sha256=digest(cr_bytes),
                  target_parent_sha256=digest(tr_bytes), implementation_sha256=digest(Path(__file__).read_bytes()),
                  index_sha256=digest(payload), production_changed=False, training_admitted=False,
                  limitations=['internal_ledger_is_not_external_publication',
                               'commit_age_is_not_api_capture_age',
                               'calendar_coverage_is_not_complete_causal_replay'])
    (out/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.base_root, args.out), indent=2))


if __name__ == '__main__':
    main()
