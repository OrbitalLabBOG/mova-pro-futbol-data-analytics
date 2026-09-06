"""Collect external public-push witnesses for pinned snapshot commit candidates."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
import gzip
import io
import json
from pathlib import Path

from mova_fpl.data.sources import _get
from experiments.data_ground_truth.bootstrap_time import aware
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked
from experiments.data_ground_truth.fixture_commit_plan import git
import hashlib
import subprocess

REPOSITORY = 'Schwetche/fpl_project'
REPOSITORY_ID = 1042951725


def extract(data, root):
    events, scanned = [], 0
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
        for line in stream:
            scanned += 1
            if REPOSITORY.encode() not in line:
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


def witness(candidate, hour, repo=None):
    matched = [e for e in hour['events'] if e['public'] is True and
        (candidate['commit'] == e['head'] or candidate['commit'] in e['commit_shas'])]
    ancestry_heads=set()
    if repo is not None:
        for event in hour['events']:
            if event in matched or event['public'] is not True or not event.get('head'):continue
            try:git(repo,'merge-base','--is-ancestor',candidate['commit'],event['head'])
            except subprocess.CalledProcessError:continue
            matched.append(event);ancestry_heads.add(event['head'])
    row = dict(season=candidate['season'], gw=candidate['gw'], path=candidate['path'],
        source_sha256=candidate['source_sha256'], commit=candidate['commit'], deadline=candidate['deadline'],
        archive_hour=hour['hour'], archive_sha256=hour['compressed_sha256'],
        status='no_matching_public_push_in_requested_hour', available_at=None, eligible_predeadline=False)
    if matched:
        event = min(matched, key=lambda e: aware(e['created_at']))
        timestamp = aware(event['created_at'])
        valid = aware(candidate['committer_at']) <= timestamp < aware(candidate['deadline'])
        row.update(event_id=event['event_id'], source_event_sha256=event['source_event_sha256'],
            public_push_at=event['created_at'], public_head=event['head'], proof_kind='ancestor_of_public_head' if event['head'] in ancestry_heads else 'exact_commit', status='public_push_before_deadline' if valid else 'push_outside_time_bounds',
            available_at=event['created_at'] if valid else None,
            eligible_predeadline=valid, evidence_grade='external_archive_of_GitHub_public_push_event')
    return row


def candidates(audit_root,raw_root,repo):
    report_bytes=(audit_root/'report.json').read_bytes();report=json.loads(report_bytes)
    raw_bytes=checked(raw_root/'manifest.json',report['source_manifest_sha256']);raw=json.loads(raw_bytes)
    if raw['repository']!=REPOSITORY:raise ValueError('wrong source repository')
    coverage=json.loads(checked(audit_root/'coverage.json',report['artifacts']['coverage.json']))
    versions=json.loads(checked(audit_root/'versions.json',report['artifacts']['versions.json']))
    by_revision={r['revision']:r for r in versions if r['path']=='data/fixtures.csv'}
    raw_by_revision={r['revision']:r for r in raw['records'] if r['path']=='data/fixtures.csv'}
    result=[]
    for c in coverage:
        if 'revision' not in c:continue
        v=by_revision[c['revision']];r=raw_by_revision[c['revision']]
        if v['season']!='2025-26' or not v['identity_verified']:raise ValueError('unverified fixture season')
        if v['normalized_sha256']!=c['normalized_sha256'] or v['source_sha256']!=r['sha256']:raise ValueError('candidate binding mismatch')
        checked(audit_root/'objects'/v['normalized_sha256'],v['normalized_sha256'])
        data=checked(raw_root/'objects'/r['sha256'],r['sha256'])
        blob=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        if blob!=r['git_blob'] or git(repo,'ls-tree',r['revision'],'--',r['path']).split()[2]!=blob:raise ValueError('fixture Git blob mismatch')
        git(repo,'merge-base','--is-ancestor',r['revision'],raw['pinned_revision'])
        if aware(git(repo,'show','-s','--format=%cI',r['revision']).strip())!=aware(r['committer_at']):raise ValueError('source Git clock mismatch')
        if r['committer_at']!=c['source_committer_at'] or aware(r['committer_at'])>=aware(c['deadline']):raise ValueError('invalid candidate time')
        result.append(dict(season='2025-26',gw=c['gw'],path=r['path'],commit=r['revision'],source_sha256=r['sha256'],
            committer_at=r['committer_at'],deadline=c['deadline'],normalized_sha256=v['normalized_sha256']))
    return report_bytes,result


def validate_event_projection(root,hour):
    for e in hour['events']:
        line=checked(root/'events'/e['source_event_sha256'],e['source_event_sha256']);raw=json.loads(line)
        if raw.get('type')!='PushEvent' or raw.get('repo',{}).get('name')!=REPOSITORY or raw['repo'].get('id')!=REPOSITORY_ID:raise ValueError('foreign publication evidence')
        payload=raw['payload']
        expected=dict(event_id=raw['id'],created_at=raw['created_at'],public=raw.get('public'),head=payload.get('head'),
            commit_shas=[c['sha'] for c in payload.get('commits',[])],source_event_sha256=digest(line))
        if e!=expected:raise ValueError('altered event projection')


def build(root:Path,audit_root:Path,raw_root:Path,repo:Path):
    report_bytes,selected=candidates(audit_root,raw_root,repo)
    hours={aware(c['committer_at']).strftime('%Y-%m-%d-%H') for c in selected}
    root.mkdir(parents=True,exist_ok=True);records={};errors=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs={pool.submit(capture_hour,root,h):h for h in sorted(hours)}
        for i,future in enumerate(as_completed(jobs),1):
            h=jobs[future]
            try:
                record=future.result();validate_event_projection(root,record);records[h]=record
            except Exception as exc:errors.append(dict(hour=h,error=type(exc).__name__))
            print(json.dumps(dict(completed_hours=i,total_hours=len(hours),errors=len(errors))),flush=True)
    followup=set()
    for c in selected:
        h=aware(c['committer_at']).strftime('%Y-%m-%d-%H')
        if h in records and not witness(c,records[h])['eligible_predeadline']:
            followup.add((datetime.strptime(h,'%Y-%m-%d-%H')+timedelta(hours=1)).strftime('%Y-%m-%d-%H'))
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs={pool.submit(capture_hour,root,h):h for h in sorted(followup-hours)}
        for future in as_completed(jobs):
            h=jobs[future]
            try:
                record=future.result();validate_event_projection(root,record);records[h]=record
            except Exception as exc:errors.append(dict(hour=h,error=type(exc).__name__))
    rows=[]
    for c in selected:
        h=aware(c['committer_at']).strftime('%Y-%m-%d-%H');next_h=(datetime.strptime(h,'%Y-%m-%d-%H')+timedelta(hours=1)).strftime('%Y-%m-%d-%H')
        options=[witness(c,records[x],repo) for x in (h,next_h) if x in records]
        valid=[r for r in options if r['eligible_predeadline']]
        if options:rows.append(dict(min(valid,key=lambda r:aware(r['available_at'])) if valid else options[0],normalized_sha256=c['normalized_sha256']))
    payload=(json.dumps(rows,indent=2)+'\n').encode();(root/'witnesses.json').write_bytes(payload)
    result=dict(version='fixture-publication-v2',repository=REPOSITORY,repository_id=REPOSITORY_ID,
        fixture_audit_sha256=digest(report_bytes),implementation_sha256=digest(Path(__file__).read_bytes()),
        expected_candidates=len(selected),expected_hours=len(hours|followup),acquired_hours=len(records),errors=errors,
        downloaded_bytes=sum(r['compressed_bytes'] for r in records.values()),public_push_witnesses=sum(r['eligible_predeadline'] for r in rows),
        assessed_candidates=len(rows),witnesses_sha256=digest(payload),
        hour_report_sha256={h:digest((root/'hours'/(h+'.json')).read_bytes()) for h in sorted(records)},
        unrelated_events_retained=False,production_changed=False,training_admitted=False,
        limitations=['one_hour_without_event_is_not_proof_of_nonpublication','publication_proof_is_not_complete_replay_readiness'])
    (root/'report.json').write_text(json.dumps(result,indent=2)+'\n');return result


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for arg in ('root','audit-root','raw-root','repo'):ap.add_argument('--'+arg,type=Path,required=True)
    a=ap.parse_args();r=build(a.root,a.audit_root,a.raw_root,a.repo);print(json.dumps(r,indent=2))
    if r['errors']:raise SystemExit(1)


if __name__=='__main__':main()
