"""Measure nominal historical snapshot coverage without admitting publication time."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
from pathlib import Path

from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked


def named_time(name):
    return datetime.strptime(name, '%Y-%m-%dT%H-%M-%SZ_data.json').replace(tzinfo=timezone.utc)


def measure(records, read_object):
    candidates = {}; seasons = {}; clocks = Counter()
    for record in records:
        data = json.loads(read_object(record['sha256']))
        season = record['content_summary']['season']
        timestamp = named_time(record['listing_item']['name'])
        declared = data.get('download_time')
        # Compare wall-clock fields only. A naive timestamp does not prove UTC capture.
        try:
            parsed = datetime.fromisoformat(declared)
            delta = abs((parsed.replace(tzinfo=None)-timestamp.replace(tzinfo=None)).total_seconds())
        except (TypeError, ValueError):
            delta = None
        clock_status = 'within_60s_wall_clock' if delta is not None and delta <= 60 else 'missing_or_disagreeing_wall_clock'
        clocks[clock_status] += 1
        stats = seasons.setdefault(season, dict(snapshots=0, players_min=None, players_max=0, player_rows=0,
            duplicate_or_missing_player_id_snapshots=0, source_hashes=set(),
            nonnull_player_fields={k:0 for k in ('code','minutes','total_points','now_cost','status','news','chance_of_playing_next_round')}))
        stats['snapshots'] += 1; stats['source_hashes'].add(record['sha256'])
        n = len(data['elements'])
        stats['players_min'] = n if stats['players_min'] is None else min(stats['players_min'], n)
        stats['players_max'] = max(stats['players_max'], n)
        stats['player_rows'] += n
        ids = [x.get('id') for x in data['elements']]
        stats['duplicate_or_missing_player_id_snapshots'] += int(None in ids or len(set(ids)) != n)
        for field in stats['nonnull_player_fields']:
            stats['nonnull_player_fields'][field] += sum(x.get(field) is not None for x in data['elements'])
        if clock_status != 'within_60s_wall_clock':
            continue
        for event in data['events']:
            deadline = datetime.fromisoformat(event['deadline_time'].replace('Z','+00:00'))
            if deadline.tzinfo is None:
                raise ValueError('deadline must declare timezone')
            age = (deadline-timestamp).total_seconds()/3600
            if not 0 < age <= 168:
                continue
            key = (season, event['id'], deadline.isoformat())
            candidate = dict(season=season, gameweek=event['id'], deadline=deadline.isoformat(),
                             nominal_snapshot_time=timestamp.isoformat(), nominal_age_hours=age,
                             source_sha256=record['sha256'], source_url=record['url'],
                             declared_download_time=declared, wall_clock_difference_seconds=delta,
                             available_at=None, eligible_predeadline=False, eligible_training=False)
            modified = record.get('response_last_modified')
            candidate['blob_last_modified_before_deadline'] = (parsedate_to_datetime(modified) < deadline) if modified else None
            if key not in candidates or (candidate['nominal_age_hours'], candidate['source_url']) < (candidates[key]['nominal_age_hours'], candidates[key]['source_url']):
                candidates[key] = candidate
    for season, stats in seasons.items():
        stats['unique_contents'] = len(stats.pop('source_hashes'))
        windows = [v for k,v in candidates.items() if k[0] == season]
        stats['deadline_variants'] = len(windows)
        stats['gameweeks_with_nominal_candidate'] = sorted({v['gameweek'] for v in windows})
        stats['gameweek_coverage_by_max_age_hours'] = {
            str(age): len({v['gameweek'] for v in windows if v['nominal_age_hours'] <= age}) for age in (1,6,24,168)}
        stats['selected_variants_blob_modified_after_or_at_deadline'] = sum(v['blob_last_modified_before_deadline'] is False for v in windows)
    return dict(seasons=seasons, wall_clock_status=dict(clocks)), [candidates[k] for k in sorted(candidates)]


def build(root, out):
    report_bytes = (root/'report.json').read_bytes()
    parent = json.loads(report_bytes)
    manifest = json.loads(checked(root/'manifest.json', parent['manifest_sha256']))
    records = manifest['records']
    if len(records) != parent['snapshots'] or len({r['url'] for r in records}) != len(records):
        raise ValueError('incomplete or duplicate manifest')
    summary, windows = measure(records, lambda sha:checked(root/'objects'/sha, sha))
    out.mkdir(parents=True,exist_ok=True)
    payload = json.dumps(windows,indent=2,allow_nan=False)+'\n'
    (out/'nominal_windows.json').write_text(payload)
    report = dict(version='azure-coverage-v1', parent_report_sha256=digest(report_bytes),
                  implementation_sha256=digest(Path(__file__).read_bytes()), **summary,
                  artifacts={'nominal_windows.json':digest(payload.encode())},
                  training_admitted=False, predeadline_admitted=False,
                  limitations=['nominal_timestamp_coverage_not_publication_proof',
                               'wall_clock_agreement_does_not_establish_timezone_or_authenticity',
                               'blob_last_modified_does_not_establish_public_access',
                               'deadline_variants_preserved_not_resolved_using_future_state',
                               'bootstrap_players_not_player_fixture_labels'])
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.root,a.out),indent=2))
