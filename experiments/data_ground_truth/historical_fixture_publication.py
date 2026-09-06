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
import re

REPOSITORY = 'vaastav/Fantasy-Premier-League'
REPOSITORY_ID = 24128688


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
    raw=json.loads(checked(raw_root/'manifest.json',report['manifest_sha256']))
    if raw['repository']!=REPOSITORY or raw['errors']:raise ValueError('wrong or incomplete source repository')
    coverage=json.loads(checked(audit_root/'nominal_candidates.json',report['artifacts']['nominal_candidates.json']))
    versions=json.loads(checked(audit_root/'versions.json',report['artifacts']['versions.json']))
    by_key={(r['season'],r['revision']):r for r in versions}
    raw_by_key={(r['season'],r['revision']):r for r in raw['records']}
    result=[]
    for c in coverage:
        if 'revision' not in c:continue
        key=(c['season'],c['revision']);v=by_key[key];r=raw_by_key[key]
        if r['path']!='data/'+c['season']+'/fixtures.csv':raise ValueError('fixture season/path mismatch')
        if v['normalized_sha256']!=c['normalized_sha256'] or v['source_sha256']!=r['sha256']:raise ValueError('candidate binding mismatch')
        checked(audit_root/'objects'/v['normalized_sha256'],v['normalized_sha256'])
        data=checked(raw_root/'objects'/r['sha256'],r['sha256'])
        blob=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        if blob!=r['git_blob'] or git(repo,'ls-tree',r['revision'],'--',r['path']).split()[2]!=blob:raise ValueError('fixture Git blob mismatch')
        git(repo,'merge-base','--is-ancestor',r['revision'],raw['pinned_revision'])
        if aware(git(repo,'show','-s','--format=%cI',r['revision']).strip())!=aware(r['committer_at']):raise ValueError('source Git clock mismatch')
        if r['committer_at']!=c['source_committer_at'] or aware(r['committer_at'])>=aware(c['deadline']):raise ValueError('invalid candidate time')
        result.append(dict(season=c['season'],gw=c['gw'],path=r['path'],commit=r['revision'],source_sha256=r['sha256'],
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


def candidate_hours(candidate,extended):
    start=aware(candidate['committer_at']).replace(minute=0,second=0,microsecond=0)
    limit=min(72,int((aware(candidate['deadline'])-start).total_seconds()//3600)) if f"{candidate['season']}:{candidate['gw']}" in extended else 1
    return [(start+timedelta(hours=i)).strftime('%Y-%m-%d-%H') for i in range(limit+1)]


def get_hour(root,hour,offline=False):
    failure=root/'failures'/(hour+'.json')
    if offline and not (root/'hours'/(hour+'.json')).exists():
        reason=json.loads(failure.read_text())['reason'] if failure.exists() else 'missing offline cache'
        raise OSError(reason)
    try:return capture_hour(root,hour)
    except OSError as exc:
        # URLs are fixed public archive URLs; retain only the sanitized terminal reason.
        match=re.search(r'\((HTTP \d{3}|URLError/[^)]+)\)$',str(exc))
        reason=match.group(1) if match else 'OSError'
        failure.parent.mkdir(parents=True,exist_ok=True)
        failure.write_text(json.dumps(dict(hour=hour,reason=reason),sort_keys=True)+'\n')
        raise OSError(reason) from None


def build(root:Path,audit_root:Path,raw_root:Path,repo:Path,extended=(),offline=False):
    report_bytes,selected=candidates(audit_root,raw_root,repo)
    if set(extended)-{f"{c['season']}:{c['gw']}" for c in selected}:raise ValueError('unknown extended candidate')
    hours={aware(c['committer_at']).strftime('%Y-%m-%d-%H') for c in selected}
    root.mkdir(parents=True,exist_ok=True);records={};errors=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs={pool.submit(get_hour,root,h,offline):h for h in sorted(hours)}
        for i,future in enumerate(as_completed(jobs),1):
            h=jobs[future]
            try:
                record=future.result();validate_event_projection(root,record);records[h]=record
            except Exception as exc:errors.append(dict(hour=h,error=type(exc).__name__,reason=str(exc) if type(exc) is OSError else None))
            print(json.dumps(dict(completed_hours=i,total_hours=len(hours),errors=len(errors))),flush=True)
    followup=set()
    for c in selected:
        h=aware(c['committer_at']).strftime('%Y-%m-%d-%H')
        if h not in records or not witness(c,records[h])['eligible_predeadline']:
            followup.update(candidate_hours(c,extended)[1:])
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs={pool.submit(get_hour,root,h,offline):h for h in sorted(followup-hours)}
        for future in as_completed(jobs):
            h=jobs[future]
            try:
                record=future.result();validate_event_projection(root,record);records[h]=record
            except Exception as exc:errors.append(dict(hour=h,error=type(exc).__name__,reason=str(exc) if type(exc) is OSError else None))
    rows=[]
    for c in selected:
        h=aware(c['committer_at']).strftime('%Y-%m-%d-%H');next_h=(datetime.strptime(h,'%Y-%m-%d-%H')+timedelta(hours=1)).strftime('%Y-%m-%d-%H')
        options=[witness(c,records[x],repo) for x in candidate_hours(c,extended) if x in records]
        valid=[r for r in options if r['eligible_predeadline']]
        if options:rows.append(dict(min(valid,key=lambda r:aware(r['available_at'])) if valid else options[0],normalized_sha256=c['normalized_sha256']))
    payload=(json.dumps(rows,indent=2)+'\n').encode();(root/'witnesses.json').write_bytes(payload)
    result=dict(version='historical-fixture-publication-v2',extended_candidates=sorted(extended),repository=REPOSITORY,repository_id=REPOSITORY_ID,
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
    ap.add_argument('--extended-candidate',action='append',default=[])
    ap.add_argument('--offline',action='store_true')
    a=ap.parse_args();r=build(a.root,a.audit_root,a.raw_root,a.repo,a.extended_candidate,a.offline);print(json.dumps(r,indent=2))
    if r['errors']:raise SystemExit(1)


if __name__=='__main__':main()
