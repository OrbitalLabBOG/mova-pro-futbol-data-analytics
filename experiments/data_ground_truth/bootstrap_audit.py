"""Measure bootstrap archive coverage; source clock is not an as-of certificate."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import lzma
from pathlib import Path

from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.bootstrap_archive import claimed_time

FIELDS = ('code', 'now_cost', 'team', 'element_type', 'status', 'news',
          'news_added', 'chance_of_playing_next_round', 'selected_by_percent',
          'total_points', 'minutes', 'expected_goals', 'expected_assists')


def decode(data: bytes, limit: int = 32 * 1024 * 1024) -> dict:
    decoder = lzma.LZMADecompressor(memlimit=256 * 1024 * 1024)
    payload = decoder.decompress(data, max_length=limit + 1)
    if len(payload) > limit or not decoder.eof or decoder.unused_data:
        raise ValueError('oversized, truncated or trailing snapshot payload')
    result = json.loads(payload)
    if not isinstance(result, dict):
        raise ValueError('snapshot must be an object')
    return result


def inspect(snapshot: dict, path: str) -> tuple[dict, list[dict]]:
    elements, events = snapshot['elements'], snapshot['events']
    if not elements or not events:
        raise ValueError('empty bootstrap population or events')
    ids = [e['id'] for e in elements]
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate bootstrap element')
    event_ids = [e['id'] for e in events]
    if len(set(event_ids)) != len(event_ids) or 1 not in event_ids:
        raise ValueError('ambiguous event calendar')
    first = next(e for e in events if e['id'] == 1)
    start = datetime.fromisoformat(first['deadline_time'].replace('Z', '+00:00'))
    if start.tzinfo is None:
        raise ValueError('naive FPL deadline')
    season = f'{start.year}-{(start.year + 1) % 100:02d}'
    players = [e for e in elements if e['element_type'] in (1, 2, 3, 4)]
    unknown = sum(e['element_type'] not in (1, 2, 3, 4, 5) for e in elements)
    clock = claimed_time(path)
    nominal = datetime.fromisoformat(clock).replace(tzinfo=timezone.utc)
    # UTC is an explicit hypothesis for coverage only, never available_at.
    candidates = []
    for event in events:
        deadline = datetime.fromisoformat(event['deadline_time'].replace('Z', '+00:00'))
        if deadline.tzinfo is None:
            raise ValueError('naive FPL deadline')
        gap = (deadline - nominal).total_seconds() / 3600
        if 0 < gap <= 48 and not event.get('finished', False):
            candidates.append(dict(season=season, gw=event['id'], deadline=event['deadline_time'],
                                   nominal_hours_before=gap, source_claimed_at=clock, path=path,
                                   eligible_predeadline=False))
    return dict(path=path, season=season, source_claimed_at=clock, players=len(players),
                managers=len(elements)-len(players)-unknown, unknown_entity_types=unknown,
                event_count=len(events),
                fields={f: dict(present=sum(f in e for e in players),
                                nonnull=sum(e.get(f) is not None for e in players)) for f in FIELDS}), candidates


def build(root: Path, out: Path) -> dict:
    raw = (root / 'manifest.json').read_bytes()
    manifest = json.loads(raw)
    if manifest['errors'] or len(manifest['records']) != manifest['expected_files']:
        raise ValueError('incomplete snapshot acquisition')
    records = [r for r in manifest['records'] if r['path'].startswith('cache/')]
    if len(records) != manifest['expected_snapshots']:
        raise ValueError('snapshot inventory count mismatch')
    rows, errors, best = [], [], {}
    for i, record in enumerate(records, 1):
        try:
            data = (root / 'objects' / record['sha256']).read_bytes()
            if digest(data) != record['sha256']:
                raise ValueError('snapshot hash mismatch')
            row, candidates = inspect(decode(data), record['path'])
            rows.append(dict(sha256=record['sha256'], **row))
            for candidate in candidates:
                key = (candidate['season'], candidate['gw'])
                if key not in best or candidate['nominal_hours_before'] < best[key]['nominal_hours_before']:
                    best[key] = dict(sha256=record['sha256'], **candidate)
        except (ValueError, KeyError, TypeError, lzma.LZMAError) as exc:
            errors.append(dict(path=record['path'], sha256=record['sha256'], error=str(exc)))
        if i % 500 == 0:
            print(json.dumps(dict(audited=i, errors=len(errors))), flush=True)
    seasons = {}
    for season in sorted({r['season'] for r in rows}):
        subset = [r for r in rows if r['season'] == season]
        dates = sorted(datetime.fromisoformat(r['source_claimed_at']) for r in subset)
        seasons[season] = dict(snapshots=len(subset), first_claimed_at=dates[0].isoformat(),
            last_claimed_at=dates[-1].isoformat(), player_snapshot_rows=sum(r['players'] for r in subset),
            manager_snapshot_rows=sum(r['managers'] for r in subset),
            unknown_entity_rows=sum(r['unknown_entity_types'] for r in subset),
            max_gap_hours=max(((b-a).total_seconds()/3600 for a,b in zip(dates, dates[1:])), default=0),
            nominal_deadlines_with_snapshot_within_48h=sorted(k[1] for k in best if k[0] == season),
            fields={f: {k: sum(r['fields'][f][k] for r in subset) for k in ('present','nonnull')} for f in FIELDS})
    out.mkdir(parents=True, exist_ok=True)
    artifacts = {}
    for name, content in [('snapshot_audit.json', rows), ('errors.json', errors),
                          ('nominal_deadline_candidates.json', [best[k] for k in sorted(best)])]:
        payload = (json.dumps(content, indent=2) + '\n').encode()
        (out / name).write_bytes(payload)
        artifacts[name] = digest(payload)
    report = dict(version='bootstrap-audit-v1', manifest_sha256=digest(raw), snapshots=len(records),
        parsed_snapshots=len(rows), errors=len(errors), seasons=seasons, artifacts=artifacts,
        clock_assumption='UTC_for_nominal_coverage_only_source_clock_has_no_timezone',
        verified_predeadline_snapshots=0, eligible_predeadline=False,
        complete_label_seasons_added=0)
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    report = build(args.root, args.out)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
