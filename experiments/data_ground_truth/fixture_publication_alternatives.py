"""Seek older fixture calendars with public witnesses, retaining explicit staleness and schedule deltas."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import timedelta
import gzip
import hashlib
import json
from pathlib import Path
from experiments.data_ground_truth.bootstrap_time import aware
from experiments.data_ground_truth.fixture_publication import capture_hour,validate_event_projection,witness,REPOSITORY,candidates as base_candidates
from experiments.data_ground_truth.fixture_commit_plan import git
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked


def alternatives(candidate,versions,max_age_hours=336):
    deadline=aware(candidate['deadline'])
    return sorted([v for v in versions if v['main_series'] and v['identity_verified'] and v['season']=='2025-26'
        and v['revision']!=candidate['commit'] and 0<(deadline-aware(v['committer_at'])).total_seconds()/3600<=max_age_hours
        and aware(v['committer_at'])<aware(candidate['source_committer_at'])],key=lambda v:(v['committer_at'],v['revision']),reverse=True)


def verify_candidate(candidate,version,raw,raw_root,audit_root,repo):
    record=next(r for r in raw['records'] if r['revision']==version['revision'] and r['path']=='data/fixtures.csv')
    if record['sha256']!=version['source_sha256'] or record['committer_at']!=version['committer_at']:raise ValueError('version binding mismatch')
    data=checked(raw_root/'objects'/record['sha256'],record['sha256'])
    checked(audit_root/'objects'/version['normalized_sha256'],version['normalized_sha256'])
    blob=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
    if blob!=record['git_blob'] or git(repo,'ls-tree',record['revision'],'--',record['path']).split()[2]!=blob:raise ValueError('raw Git mismatch')
    git(repo,'merge-base','--is-ancestor',record['revision'],raw['pinned_revision'])
    if aware(git(repo,'show','-s','--format=%cI',record['revision']))!=aware(record['committer_at']):raise ValueError('Git clock mismatch')
    return dict(season='2025-26',gw=candidate['gw'],deadline=candidate['deadline'],path=record['path'],commit=record['revision'],
        source_sha256=record['sha256'],committer_at=record['committer_at'],normalized_sha256=version['normalized_sha256'])


def build(publication_root:Path,audit_root:Path,raw_root:Path,repo:Path,out:Path):
    pub_bytes=(publication_root/'report.json').read_bytes();pub=json.loads(pub_bytes)
    previous=json.loads(checked(publication_root/'witnesses.json',pub['witnesses_sha256']))
    audit_bytes=checked(audit_root/'report.json',pub['fixture_audit_sha256']);audit=json.loads(audit_bytes)
    versions=json.loads(checked(audit_root/'versions.json',audit['artifacts']['versions.json']))
    coverage=json.loads(checked(audit_root/'coverage.json',audit['artifacts']['coverage.json']));by_gw={r['gw']:r for r in coverage}
    raw=json.loads(checked(raw_root/'manifest.json',audit['source_manifest_sha256']))
    if raw['repository']!=REPOSITORY:raise ValueError('wrong source repository')
    holes=[dict(r,source_committer_at=by_gw[r['gw']]['source_committer_at']) for r in previous if not r['eligible_predeadline']]
    plan={r['gw']:alternatives(r,versions) for r in holes};resolved={};attempts=[];records={};errors=[]
    out.mkdir(parents=True,exist_ok=True)
    for index in range(max(map(len,plan.values()),default=0)):
        choices=[verify_candidate(r,plan[r['gw']][index],raw,raw_root,audit_root,repo) for r in holes if r['gw'] not in resolved and index<len(plan[r['gw']])]
        if not choices:break
        hours={h for c in choices for h in [aware(c['committer_at']).strftime('%Y-%m-%d-%H'),(aware(c['committer_at'])+timedelta(hours=1)).strftime('%Y-%m-%d-%H')]}
        with ThreadPoolExecutor(max_workers=4) as pool:
            jobs={pool.submit(capture_hour,out,h):h for h in sorted(hours-set(records))}
            for future in as_completed(jobs):
                h=jobs[future]
                try:
                    record=future.result();validate_event_projection(out,record);records[h]=record
                except Exception as exc:errors.append(dict(hour=h,error=type(exc).__name__))
        for c in choices:
            hs=[aware(c['committer_at']).strftime('%Y-%m-%d-%H'),(aware(c['committer_at'])+timedelta(hours=1)).strftime('%Y-%m-%d-%H')]
            proofs=[witness(c,records[h],repo) for h in hs if h in records];valid=[r for r in proofs if r['eligible_predeadline']]
            attempts.append(dict(gw=c['gw'],commit=c['commit'],hours=hs,proven=bool(valid)))
            if valid:
                proof=min(valid,key=lambda r:aware(r['available_at']));original=by_gw[c['gw']]
                a=json.loads(gzip.decompress(checked(audit_root/'objects'/original['normalized_sha256'],original['normalized_sha256'])))
                b=json.loads(gzip.decompress(checked(audit_root/'objects'/c['normalized_sha256'],c['normalized_sha256'])))
                old={r['id']:r for r in b};deltas=[]
                for r in a:
                    for field in ('event','kickoff_time','team_h','team_a','code'):
                        if r.get(field)!=old[r['id']].get(field):deltas.append(dict(fixture=r['id'],field=field,earlier=old[r['id']].get(field),later_unproven=r.get(field)))
                resolved[c['gw']]=dict(proof,normalized_sha256=c['normalized_sha256'],source_committer_at=c['committer_at'],
                    nominal_commit_age_hours=(aware(c['deadline'])-aware(c['committer_at'])).total_seconds()/3600,
                    older_than_original_hours=(aware(original['source_committer_at'])-aware(c['committer_at'])).total_seconds()/3600,
                    schedule_deltas=deltas)
        print(json.dumps(dict(round=index+1,attempts=len(attempts),resolved=len(resolved),hours=len(records),errors=len(errors))),flush=True)
    _,verified_base=base_candidates(audit_root,raw_root,repo)
    verified_by_gw={c['gw']:c for c in verified_base};selected=[]
    for original in previous:
        gw=original['gw']
        if original['eligible_predeadline']:
            h=original['archive_hour']
            hour=json.loads(checked(publication_root/'hours'/(h+'.json'),pub['hour_report_sha256'][h]))
            validate_event_projection(publication_root,hour)
            proof=witness(verified_by_gw[gw],hour,repo)
            if dict(proof,normalized_sha256=verified_by_gw[gw]['normalized_sha256'])!=original:raise ValueError('parent witness no longer verifies')
            c=verified_by_gw[gw]
            selected.append(dict(gw=gw,deadline=c['deadline'],source_committer_at=c['committer_at'],
                normalized_sha256=c['normalized_sha256'],source_sha256=c['source_sha256'],proof=proof,evidence_origin='G28'))
        elif gw in resolved:
            r=resolved[gw]
            selected.append(dict(gw=gw,deadline=r['deadline'],source_committer_at=r['source_committer_at'],
                normalized_sha256=r['normalized_sha256'],source_sha256=r['source_sha256'],proof=r,evidence_origin='G29'))
    artifacts={}
    for name,value in [('plan.json',plan),('attempts.json',attempts),('replacements.json',[resolved[k] for k in sorted(resolved)]),('selected_calendars.json',selected)]:
        data=(json.dumps(value,indent=2)+'\n').encode();(out/name).write_bytes(data);artifacts[name]=digest(data)
    report=dict(version='fixture-publication-alternatives-v1',parent_publication_report_sha256=digest(pub_bytes),
        fixture_audit_sha256=digest(audit_bytes),implementation_sha256=digest(Path(__file__).read_bytes()),max_nominal_age_hours=336,
        selected_calendars=len(selected),holes=len(holes),planned_candidates=sum(map(len,plan.values())),attempts=len(attempts),resolved=len(resolved),
        unresolved_gws=sorted(set(plan)-set(resolved)),acquired_hours=len(records),downloaded_bytes=sum(r['compressed_bytes'] for r in records.values()),
        errors=errors,hour_report_sha256={h:digest((out/'hours'/(h+'.json')).read_bytes()) for h in sorted(records)},artifacts=artifacts,
        production_changed=False,training_admitted=False,limitations=['older_calendar_is_not_the_latest_unproven_calendar','publication_is_not_API_capture_time','schedule_deltas_are_retrospective_diagnostics'])
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('publication-root','audit-root','raw-root','repo','out'):ap.add_argument('--'+name,type=Path,required=True)
    a=ap.parse_args();print(json.dumps(build(a.publication_root,a.audit_root,a.raw_root,a.repo,a.out),indent=2))


if __name__=='__main__':main()
