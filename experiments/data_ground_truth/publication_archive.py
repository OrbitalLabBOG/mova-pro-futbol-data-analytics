"""Collect external public-push witnesses for pinned snapshot commit candidates."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import gzip
import io
import json
from pathlib import Path

from mova_fpl.data.sources import _get
from experiments.data_ground_truth.bootstrap_time import aware
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked

REPOSITORY = 'Randdalf/fplcache'
REPOSITORY_ID = 359131220


def extract(data, root):
    events, scanned = [], 0
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
        for line in stream:
            scanned += 1
            if b'Randdalf/fplcache' not in line:
                continue
            event = json.loads(line)
            if event.get('type') != 'PushEvent' or event.get('repo', {}).get('name') != REPOSITORY or event['repo'].get('id') != REPOSITORY_ID:
                continue
            # Preserve exact relevant source records, not unrelated GitHub activity.
            sha = digest(line)
            (root/'events').mkdir(parents=True, exist_ok=True)
            target = root/'events'/sha
            if target.exists():
                checked(target, sha)
            else:
                target.write_bytes(line)
            payload = event['payload']
            events.append(dict(event_id=event['id'], created_at=event['created_at'], public=event.get('public'),
                head=payload.get('head'), commit_shas=[c['sha'] for c in payload.get('commits', [])],
                source_event_sha256=sha))
    return events, scanned


def capture_hour(root, hour):
    instant = datetime.strptime(hour, '%Y-%m-%d-%H')
    path = root/'hours'/(hour+'.json')
    if path.exists():
        record = json.loads(path.read_text())
        for event in record['events']:
            checked(root/'events'/event['source_event_sha256'], event['source_event_sha256'])
        return record
    # GH Archive object keys use an unpadded hour, unlike our sortable cache keys.
    url = 'https://data.gharchive.org/'+instant.strftime('%Y-%m-%d-')+str(instant.hour)+'.json.gz'
    data, headers = _get(url, include_headers=True)
    events, scanned = extract(data, root)
    record = dict(hour=hour, url=url, fetched_at=datetime.now(timezone.utc).isoformat(),
        compressed_sha256=digest(data), compressed_bytes=len(data), scanned_events=scanned,
        last_modified=headers.get('last-modified'), events=events, unrelated_events_retained=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(record, indent=2)+'\n')
    temporary.replace(path)
    return record


def witness(candidate, hour):
    matched = [e for e in hour['events'] if e['public'] is True and
        (candidate['commit'] == e['head'] or candidate['commit'] in e['commit_shas'])]
    row = dict(season=candidate['season'], gw=candidate['gw'], path=candidate['path'],
        source_sha256=candidate['source_sha256'], commit=candidate['commit'], deadline=candidate['deadline'],
        archive_hour=hour['hour'], archive_sha256=hour['compressed_sha256'],
        status='no_matching_public_push_in_requested_hour', available_at=None, eligible_predeadline=False)
    if matched:
        event = min(matched, key=lambda e: aware(e['created_at']))
        timestamp = aware(event['created_at'])
        valid = aware(candidate['committer_at']) <= timestamp < aware(candidate['deadline'])
        row.update(event_id=event['event_id'], source_event_sha256=event['source_event_sha256'],
            public_push_at=event['created_at'], status='public_push_before_deadline' if valid else 'push_outside_time_bounds',
            available_at=event['created_at'] if valid else None,
            eligible_predeadline=valid, evidence_grade='external_archive_of_GitHub_public_push_event')
    return row


def build(root: Path, provenance_root: Path):
    report_bytes = (provenance_root/'report.json').read_bytes()
    report = json.loads(report_bytes)
    candidates = json.loads(checked(provenance_root/'candidates.json', report['artifacts']['candidates.json']))
    if report['coherent_candidates'] != report['candidates'] or len(candidates) != report['candidates']:
        raise ValueError('unresolved Git candidate coherence')
    hours = {aware(c['committer_at']).strftime('%Y-%m-%d-%H') for c in candidates}
    root.mkdir(parents=True, exist_ok=True)
    records, errors = {}, []
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = {pool.submit(capture_hour, root, hour): hour for hour in sorted(hours)}
        for i, future in enumerate(as_completed(jobs), 1):
            hour = jobs[future]
            try:
                records[hour] = future.result()
            except Exception as exc:
                errors.append(dict(hour=hour, error=type(exc).__name__))
            if i % 10 == 0:
                print(json.dumps(dict(completed_hours=i, total_hours=len(hours), errors=len(errors))), flush=True)
    rows = []
    for candidate in candidates:
        hour = aware(candidate['committer_at']).strftime('%Y-%m-%d-%H')
        if hour in records:
            rows.append(witness(candidate, records[hour]))
    payload = (json.dumps(rows, indent=2)+'\n').encode()
    (root/'witnesses.json').write_bytes(payload)
    result = dict(version='publication-archive-v1', git_provenance_report_sha256=digest(report_bytes),
        implementation_sha256=digest(Path(__file__).read_bytes()), expected_candidates=len(candidates),
        expected_hours=len(hours), acquired_hours=len(records), errors=errors,
        downloaded_bytes=sum(r['compressed_bytes'] for r in records.values()),
        public_push_witnesses=sum(r['eligible_predeadline'] for r in rows), assessed_candidates=len(rows),
        witnesses_sha256=digest(payload),
        hour_report_sha256={h:digest((root/'hours'/(h+'.json')).read_bytes()) for h in sorted(records)},
        limitation='missing_event_in_one_hour_is_not_proof_of_non_publication',
        unrelated_events_retained=False, production_changed=False)
    (root/'report.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, required=True)
    ap.add_argument('--provenance-root', type=Path, required=True)
    args = ap.parse_args()
    result = build(args.root, args.provenance_root)
    print(json.dumps(result, indent=2))
    if result['errors']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
