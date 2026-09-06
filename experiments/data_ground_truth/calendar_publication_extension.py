"""Search later archive hours for missing calendar publication, retaining pushes and merges."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import gzip
import io
import json
from pathlib import Path

from mova_fpl.data.sources import _get
from experiments.data_ground_truth import historical_fixture_publication as push
from experiments.data_ground_truth import historical_pr_publication as merge
from experiments.data_ground_truth.bootstrap_time import aware
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked


def validate(root, hour):
    push.validate_event_projection(root, dict(hour, events=hour['push_events']))
    for event in hour['merge_events']:
        if merge.project(checked(root/'events'/event['source_event_sha256'],event['source_event_sha256']))!=event:
            raise ValueError('altered merge event')


def capture(root,hour,offline=False):
    path=root/'hours'/(hour+'.json')
    if path.exists():
        result=json.loads(path.read_text());validate(root,result);return result
    if offline:raise OSError('missing offline hour')
    t=datetime.strptime(hour,'%Y-%m-%d-%H');url='https://data.gharchive.org/'+t.strftime('%Y-%m-%d-')+str(t.hour)+'.json.gz'
    data,headers=_get(url,include_headers=True)
    pushes,scanned=push.extract(data,root);merges=[]
    for line in gzip.GzipFile(fileobj=io.BytesIO(data)):
        if str(push.REPOSITORY_ID).encode() not in line:continue
        event=merge.project(line)
        if event is None:continue
        (root/'events').mkdir(parents=True,exist_ok=True)
        target=root/'events'/event['source_event_sha256']
        if target.exists():checked(target,event['source_event_sha256'])
        else:target.write_bytes(line)
        merges.append(event)
    result=dict(hour=hour,url=url,fetched_at=datetime.now(timezone.utc).isoformat(),
                compressed_sha256=digest(data),compressed_bytes=len(data),scanned_events=scanned,
                last_modified=headers.get('last-modified'),push_events=pushes,merge_events=merges)
    path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(result,indent=2)+'\n');tmp.replace(path)
    validate(root,result);return result


def scheduled_hour(candidate,offset):
    if offset<2:raise ValueError('extension starts after two original hours')
    start=aware(candidate['committer_at']).replace(minute=0,second=0,microsecond=0)
    t=start+timedelta(hours=offset)
    return t.strftime('%Y-%m-%d-%H') if t<aware(candidate['deadline']) else None


def proof(candidate,hour,repo):
    a=push.witness(candidate,dict(hour,events=hour['push_events']),repo)
    b=merge.witness(candidate,dict(hour,events=hour['merge_events']),repo)
    valid=[]
    if a['eligible_predeadline']:valid.append(dict(a,evidence_type='PushEvent'))
    if b:valid.append(dict(b,evidence_type='PullRequestEvent'))
    return min(valid,key=lambda r:aware(r['available_at'])) if valid else None


def build(base,out,max_offset=24,offline=False):
    if not 2<=max_offset<=336:raise ValueError('extension bound must be 2..336 hours')
    parent_bytes=(base/'calendar-carryforward-v2/report.json').read_bytes();parent=json.loads(parent_bytes)
    # Revalidate original candidate bytes, normalized objects, Git blobs, ancestry and clock.
    audit_bytes,candidates=push.candidates(base/'fixture-history-audit-v1',base/'raw-fixture-history-v1',base/'fixtures-git-provenance')
    missing={(r['season'],r['gw']) for r in parent['missing']}
    targets=[c for c in candidates if (c['season'],c['gw']) in missing]
    if len(targets)!=len(missing):raise ValueError('missing candidate mismatch')
    records={};selected={};errors=[];attempted=set()
    for offset in range(2,max_offset+1):
        active=[c for c in targets if (c['season'],c['gw']) not in selected]
        hours={h for c in active if (h:=scheduled_hour(c,offset)) is not None}
        if not hours:break
        with ThreadPoolExecutor(max_workers=4) as pool:
            jobs={pool.submit(capture,out,h,offline):h for h in sorted(hours-attempted)}
            attempted|=hours
            for future in as_completed(jobs):
                h=jobs[future]
                try:records[h]=future.result()
                except Exception as exc:errors.append(dict(hour=h,error=type(exc).__name__))
        for c in active:
            h=scheduled_hour(c,offset)
            if h in records:
                found=proof(c,records[h],base/'fixtures-git-provenance')
                if found:selected[(c['season'],c['gw'])]=dict(found,normalized_sha256=c['normalized_sha256'],source_committer_at=c['committer_at'])
        print(json.dumps(dict(offset=offset,hours=len(records),resolved=len(selected),errors=len(errors))),flush=True)
    out.mkdir(parents=True,exist_ok=True);payload=(json.dumps([selected[k] for k in sorted(selected)],indent=2)+'\n').encode();(out/'witnesses.json').write_bytes(payload)
    result=dict(version='calendar-publication-extension-v1',parent_report_sha256=digest(parent_bytes),fixture_audit_sha256=digest(audit_bytes),
                implementation_sha256=digest(Path(__file__).read_bytes()),max_offset=max_offset,targets=len(targets),resolved=len(selected),
                unresolved=[dict(season=c['season'],gw=c['gw']) for c in targets if (c['season'],c['gw']) not in selected],
                acquired_hours=len(records),downloaded_bytes=sum(r['compressed_bytes'] for r in records.values()),
                errors=sorted(errors,key=lambda r:r['hour']),hour_report_sha256={h:digest((out/'hours'/(h+'.json')).read_bytes()) for h in sorted(records)},
                witnesses_sha256=digest(payload),production_changed=False,training_admitted=False,
                limitations=['missing_event_not_proof_of_nonpublication','parent_selection_not_rewritten','publication_not_API_capture_time'])
    (out/'report.json').write_text(json.dumps(result,indent=2)+'\n');return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base-root',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--max-offset',type=int,default=24);p.add_argument('--offline',action='store_true');a=p.parse_args()
    r=build(a.base_root,a.out,a.max_offset,a.offline);print(json.dumps({k:v for k,v in r.items() if k!='hour_report_sha256'},indent=2))
    if r['errors']:raise SystemExit(1)


if __name__=='__main__':main()
