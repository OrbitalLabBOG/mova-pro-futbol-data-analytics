"""Supplement fixture publication evidence with public, closed-and-merged pull request events."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone,timedelta
import gzip
import io
import json
from pathlib import Path
import re
import subprocess
from mova_fpl.data.sources import _get
from experiments.data_ground_truth import historical_fixture_publication as push
from experiments.data_ground_truth.bootstrap_time import aware
from experiments.data_ground_truth.fixture_commit_plan import git
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked


def project(line):
    e=json.loads(line);p=e.get('payload',{});pr=p.get('pull_request',{})
    if e.get('type')!='PullRequestEvent' or e.get('public') is not True or e.get('repo',{}).get('id')!=push.REPOSITORY_ID or e['repo'].get('name')!=push.REPOSITORY:return None
    if p.get('action')!='closed' or pr.get('merged') is not True or pr.get('base',{}).get('repo',{}).get('id')!=push.REPOSITORY_ID:return None
    sha=pr.get('merge_commit_sha')
    if not isinstance(sha,str) or not re.fullmatch('[0-9a-f]{40}',sha) or not pr.get('merged_at'):return None
    return dict(event_id=e['id'],created_at=e['created_at'],merged_at=pr['merged_at'],merge_commit_sha=sha,source_event_sha256=digest(line))


def capture(root,hour,offline=False):
    path=root/'hours'/(hour+'.json');failure=root/'failures'/(hour+'.json')
    if path.exists():
        r=json.loads(path.read_text())
        for e in r['events']:
            if project(checked(root/'events'/e['source_event_sha256'],e['source_event_sha256']))!=e:raise ValueError('altered merge event projection')
        return r
    if offline or failure.exists():raise OSError(json.loads(failure.read_text())['reason'] if failure.exists() else 'missing offline cache')
    t=datetime.strptime(hour,'%Y-%m-%d-%H');url='https://data.gharchive.org/'+t.strftime('%Y-%m-%d-')+str(t.hour)+'.json.gz'
    try:data,headers=_get(url,include_headers=True)
    except OSError as exc:
        match=re.search(r'\((HTTP \d{3}|URLError/[^)]+)\)$',str(exc));reason=match.group(1) if match else 'OSError'
        failure.parent.mkdir(parents=True,exist_ok=True);failure.write_text(json.dumps(dict(hour=hour,reason=reason),sort_keys=True)+'\n');raise OSError(reason) from None
    events=[];scanned=0;(root/'events').mkdir(parents=True,exist_ok=True)
    for line in gzip.GzipFile(fileobj=io.BytesIO(data)):
        scanned+=1
        if str(push.REPOSITORY_ID).encode() not in line:continue
        e=project(line)
        if e is None:continue
        target=root/'events'/e['source_event_sha256']
        if target.exists():checked(target,e['source_event_sha256'])
        else:target.write_bytes(line)
        events.append(e)
    r=dict(hour=hour,url=url,fetched_at=datetime.now(timezone.utc).isoformat(),compressed_sha256=digest(data),compressed_bytes=len(data),
        last_modified=headers.get('last-modified'),scanned_events=scanned,events=events,unrelated_events_retained=False)
    path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_suffix('.tmp');temp.write_text(json.dumps(r,indent=2)+'\n');temp.replace(path);return r


def witness(c,hour,repo):
    valid=[]
    for e in hour['events']:
        if not aware(c['committer_at'])<=aware(e['merged_at'])<=aware(e['created_at'])<aware(c['deadline']):continue
        if c['commit']==e['merge_commit_sha']:kind='exact_public_merge_commit'
        else:
            try:git(repo,'merge-base','--is-ancestor',c['commit'],e['merge_commit_sha'])
            except subprocess.CalledProcessError:continue
            kind='ancestor_of_public_merge_commit'
        valid.append(dict(season=c['season'],gw=c['gw'],deadline=c['deadline'],commit=c['commit'],path=c['path'],source_sha256=c['source_sha256'],
            normalized_sha256=c['normalized_sha256'],archive_hour=hour['hour'],archive_sha256=hour['compressed_sha256'],
            available_at=e['created_at'],eligible_predeadline=True,proof_kind=kind,**e))
    return min(valid,key=lambda r:aware(r['available_at'])) if valid else None


def build(publication_root,audit_root,raw_root,repo,out,offline=False):
    parent_bytes=(publication_root/'report.json').read_bytes();parent=json.loads(parent_bytes)
    audit_bytes,candidates=push.candidates(audit_root,raw_root,repo)
    if digest(audit_bytes)!=parent['fixture_audit_sha256']:raise ValueError('parent audit mismatch')
    previous=json.loads(checked(publication_root/'witnesses.json',parent['witnesses_sha256']));by_key={(r['season'],r['gw']):r for r in previous}
    selected={};holes=[]
    for c in candidates:
        key=(c['season'],c['gw']);old=by_key.get(key)
        if old and old['eligible_predeadline']:
            h=old['archive_hour'];hour=json.loads(checked(publication_root/'hours'/(h+'.json'),parent['hour_report_sha256'][h]));push.validate_event_projection(publication_root,hour)
            proof=dict(push.witness(c,hour,repo),normalized_sha256=c['normalized_sha256'])
            if proof!=old:raise ValueError('parent push proof mismatch')
            selected[key]=dict(old,source_committer_at=c['committer_at'],evidence_type='PushEvent')
        else:holes.append(c)
    records={};errors=[];attempted=set()
    for offset in (0,1):
        active=[c for c in holes if (c['season'],c['gw']) not in selected]
        hours={(aware(c['committer_at'])+timedelta(hours=offset)).strftime('%Y-%m-%d-%H') for c in active}
        with ThreadPoolExecutor(max_workers=4) as pool:
            jobs={pool.submit(capture,out,h,offline):h for h in sorted(hours-attempted)};attempted|=hours
            for future in as_completed(jobs):
                h=jobs[future]
                try:records[h]=future.result()
                except Exception as exc:errors.append(dict(hour=h,error=type(exc).__name__,reason=str(exc) if type(exc) is OSError else None))
        for c in active:
            h=(aware(c['committer_at'])+timedelta(hours=offset)).strftime('%Y-%m-%d-%H')
            if h in records:
                proof=witness(c,records[h],repo)
                if proof:selected[(c['season'],c['gw'])]=dict(proof,source_committer_at=c['committer_at'],evidence_type='PullRequestEvent')
        print(json.dumps(dict(round=offset+1,selected=len(selected),acquired_hours=len(records),errors=len(errors))),flush=True)
    out.mkdir(parents=True,exist_ok=True);rows=[selected[k] for k in sorted(selected)];payload=(json.dumps(rows,indent=2)+'\n').encode();(out/'selected_calendars.json').write_bytes(payload)
    report=dict(version='historical-pr-publication-v1',parent_publication_sha256=digest(parent_bytes),fixture_audit_sha256=digest(audit_bytes),implementation_sha256=digest(Path(__file__).read_bytes()),
        candidates=len(candidates),parent_proven=len(candidates)-len(holes),added_merge_witnesses=len(selected)-(len(candidates)-len(holes)),selected_calendars=len(selected),
        coverage={s:sum(r['season']==s for r in rows) for s in sorted({c['season'] for c in candidates})},
        unresolved=[dict(season=c['season'],gw=c['gw']) for c in candidates if (c['season'],c['gw']) not in selected],
        acquired_hours=len(records),downloaded_bytes=sum(r['compressed_bytes'] for r in records.values()),errors=sorted(errors,key=lambda r:r['hour']),
        hour_report_sha256={h:digest((out/'hours'/(h+'.json')).read_bytes()) for h in sorted(records)},selected_sha256=digest(payload),
        production_changed=False,training_admitted=False,limitations=['public_merge_time_is_not_API_capture_time','source_schedule_freshness_is_separate_from_publication'])
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('publication-root','audit-root','raw-root','repo','out'):ap.add_argument('--'+name,type=Path,required=True)
    ap.add_argument('--offline',action='store_true');a=ap.parse_args();r=build(a.publication_root,a.audit_root,a.raw_root,a.repo,a.out,a.offline)
    print(json.dumps({k:v for k,v in r.items() if k!='hour_report_sha256'},indent=2))


if __name__=='__main__':main()
