"""Audit identity variants across the full bootstrap archive without merging people."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path

from experiments.data_ground_truth.bootstrap_archive import claimed_time
from experiments.data_ground_truth.bootstrap_audit import decode
from experiments.data_ground_truth.training_dataset import checked
from experiments.data_ground_truth.raw import digest


def observe(registry, snapshot, record):
    first = [e for e in snapshot['events'] if e['id'] == 1]
    if len(first) != 1:
        raise ValueError('ambiguous season calendar')
    year = datetime.fromisoformat(first[0]['deadline_time'].replace('Z', '+00:00')).year
    season = f'{year}-{(year+1)%100:02d}'
    clock = claimed_time(record['path'])
    elements = snapshot['elements']
    if len({e['id'] for e in elements}) != len(elements):
        raise ValueError('duplicate element')
    # Validate the whole snapshot before adding any witness to the registry.
    for e in elements:
        for field in ('id', 'code', 'element_type', 'team'):
            if type(e[field]) is not int or e[field] <= 0:
                raise ValueError('invalid identity integer')
        if e['element_type'] not in (1, 2, 3, 4, 5):
            raise ValueError('unknown entity type')
        if not isinstance(e['first_name'], str) or not isinstance(e['second_name'], str):
            raise ValueError('invalid name observation')
    for e in elements:
        key = (season, e['id'])
        variant = (e['code'], e['first_name'], e['second_name'], e['element_type'])
        bucket = registry.setdefault(key, {}).setdefault(variant, dict(
            count=0, hashes=set(), teams=set(), first=None, last=None))
        witness = dict(source_claimed_at=clock, path=record['path'], sha256=record['sha256'])
        bucket['count'] += 1
        bucket['hashes'].add(record['sha256'])
        bucket['teams'].add(e['team'])
        if bucket['first'] is None or clock < bucket['first']['source_claimed_at']:
            bucket['first'] = witness
        if bucket['last'] is None or clock > bucket['last']['source_claimed_at']:
            bucket['last'] = witness


def summarize(registry):
    entries = []
    code_owners = defaultdict(set)
    for (season, element), variants in sorted(registry.items()):
        rows = []
        for (code, first_name, second_name, position), data in sorted(variants.items()):
            rows.append(dict(code=code, first_name=first_name, second_name=second_name,
                position=position, observations=data['count'], distinct_snapshot_objects=len(data['hashes']),
                observed_team_ids=sorted(data['teams']), first=data['first'], last=data['last']))
            code_owners[(season, code)].add(element)
        entries.append(dict(season=season, element=element, variants=rows,
            code_count=len({r['code'] for r in rows}),
            name_count=len({(r['first_name'], r['second_name']) for r in rows}),
            entity_types=sorted({r['position'] for r in rows})))
    collisions = [dict(season=s, code=c, elements=sorted(ids)) for (s,c),ids in sorted(code_owners.items()) if len(ids)>1]
    return entries, collisions


def build(root: Path, out: Path):
    raw = (root/'manifest.json').read_bytes()
    manifest = json.loads(raw)
    if manifest['errors'] or len(manifest['records']) != manifest['expected_files']:
        raise ValueError('incomplete acquisition')
    records = [r for r in manifest['records'] if r['path'].startswith('cache/')]
    if len(records) != manifest['expected_snapshots']:
        raise ValueError('incomplete snapshots')
    registry, errors = {}, []
    for i, record in enumerate(records, 1):
        # Integrity failures abort rather than count corrupted content as a valid witness.
        snapshot = decode(checked(root/'objects'/record['sha256'], record['sha256']))
        try:
            observe(registry, snapshot, record)
        except (ValueError, KeyError, TypeError) as exc:
            errors.append(dict(path=record['path'], sha256=record['sha256'], error=str(exc)))
        if i % 500 == 0:
            print(json.dumps(dict(audited=i, errors=len(errors))), flush=True)
    entries, collisions = summarize(registry)
    changed = [r for r in entries if r['code_count'] > 1]
    seasons = {}
    for season in sorted({r['season'] for r in entries}):
        subset = [r for r in entries if r['season'] == season]
        seasons[season] = dict(elements=len(subset), code_changes=sum(r['code_count']>1 for r in subset),
            name_changes=sum(r['name_count']>1 for r in subset),
            managers=sum(5 in r['entity_types'] for r in subset),
            code_collisions=sum(r['season']==season for r in collisions))
    out.mkdir(parents=True, exist_ok=True)
    artifacts = {}
    for name, content in [('registry.json', entries), ('code_changes.json', changed),
                          ('code_collisions.json', collisions), ('errors.json', errors)]:
        payload = (json.dumps(content, indent=2)+'\n').encode()
        (out/name).write_bytes(payload)
        artifacts[name] = digest(payload)
    report = dict(version='bootstrap-identity-v1', manifest_sha256=digest(raw),
        implementation_sha256=digest(Path(__file__).read_bytes()), snapshots=len(records),
        errors=len(errors), elements=len(entries), elements_with_code_changes=len(changed),
        code_collisions=len(collisions), seasons=seasons, artifacts=artifacts,
        eligible_identity_repair=False, eligible_predeadline=False,
        limitation='variants_are_source_observations_not_automatic_person_equivalence')
    (out/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    print(json.dumps(build(args.root, args.out), indent=2))


if __name__ == '__main__':
    main()
