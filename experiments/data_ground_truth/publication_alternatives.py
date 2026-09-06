"""Search earlier immutable snapshots for missing public-push witnesses, within 48h."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timezone
import json
from pathlib import Path

from experiments.data_ground_truth.bootstrap_audit import decode, inspect
from experiments.data_ground_truth.bootstrap_time import aware
from experiments.data_ground_truth.publication_archive import capture_hour, witness
from experiments.data_ground_truth.publication_coverage import verify_event
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked


def eligible_alternative(original, snapshot):
    if not snapshot.get('single_addition') or not snapshot.get('author_committer_agree') or not snapshot.get('nonnegative_commit_delay'):
        return False
    clock = aware(snapshot['source_claimed_at']+'+00:00')
    original_clock = aware(original['source_claimed_at']+'+00:00')
    gap = (aware(original['deadline'])-clock).total_seconds()/3600
    return clock < original_clock and 0 < gap <= 48 and aware(snapshot['committer_at']) < aware(original['deadline'])


def verify_hour(root, record):
    for event in record['events']:
        verify_event(event, checked(root/'events'/event['source_event_sha256'], event['source_event_sha256']))


def plan(raw_root, provenance_root, archive_root):
    provenance_bytes = (provenance_root/'report.json').read_bytes()
    provenance = json.loads(provenance_bytes)
    manifest_bytes = checked(raw_root/'manifest.json', provenance['source_manifest_sha256'])
    manifest = json.loads(manifest_bytes)
    records = {r['path']:r for r in manifest['records']}
    originals = json.loads(checked(provenance_root/'candidates.json', provenance['artifacts']['candidates.json']))
    snapshots = json.loads(checked(provenance_root/'snapshots.json', provenance['artifacts']['snapshots.json']))
    archive_bytes = (archive_root/'report.json').read_bytes()
    archive = json.loads(archive_bytes)
    if archive['git_provenance_report_sha256'] != digest(provenance_bytes):
        raise ValueError('publication provenance mismatch')
    old_witnesses = json.loads(checked(archive_root/'witnesses.json', archive['witnesses_sha256']))
    indexed = {(r['season'],r['gw']):r for r in old_witnesses}
    if len(indexed) != len(old_witnesses):
        raise ValueError('duplicate original witnesses')
    jobs, preserved, excluded = [], [], []
    for c in originals:
        old = indexed.get((c['season'],c['gw']))
        if old:
            hour = old['archive_hour']
            hour_record = json.loads(checked(archive_root/'hours'/(hour+'.json'),archive['hour_report_sha256'][hour]))
            verify_hour(archive_root,hour_record)
            if witness(c,hour_record) != old:
                raise ValueError('original witness derivation mismatch')
        if old and old['eligible_predeadline']:
            preserved.append(dict(candidate=c,witness=old))
            continue
        alternatives = []
        for s in sorted(snapshots,key=lambda x:x['source_claimed_at'],reverse=True):
            if not eligible_alternative(c,s):
                continue
            if records[s['path']]['sha256'] != s['source_sha256']:
                raise ValueError('alternative source mismatch')
            snapshot = decode(checked(raw_root/'objects'/s['source_sha256'],s['source_sha256']))
            _, possible = inspect(snapshot,s['path'])
            matching = [x for x in possible if x['season']==c['season'] and x['gw']==c['gw'] and x['deadline']==c['deadline']]
            if len(matching)!=1:
                excluded.append(dict(season=c['season'],gw=c['gw'],path=s['path'],reason='snapshot_calendar_mismatch'))
                continue
            alternatives.append(dict(s,season=c['season'],gw=c['gw'],deadline=c['deadline']))
        jobs.append(dict(original=c,alternatives=alternatives))
    return dict(version='publication-alternatives-plan-v1',source_manifest_sha256=digest(manifest_bytes),
        provenance_report_sha256=digest(provenance_bytes),archive_report_sha256=digest(archive_bytes),
        original_candidates=len(originals),preserved=preserved,jobs=jobs,excluded=excluded,
        selection_rule='latest_earlier_immutable_snapshot_with_same_deadline_within_48h_and_public_push_proof')


def run(raw_root:Path,provenance_root:Path,archive_root:Path,out:Path):
    out.mkdir(parents=True,exist_ok=True)
    input_plan = plan(raw_root,provenance_root,archive_root)
    payload = (json.dumps(input_plan,indent=2)+'\n').encode()
    plan_path=out/'plan.json'
    if plan_path.exists() and plan_path.read_bytes()!=payload:
        raise ValueError('existing plan changed; use a new output root')
    plan_path.write_bytes(payload)
    pending = sorted(input_plan['jobs'],key=lambda j:(j['original']['season'],j['original']['gw']),reverse=True)
    found, attempts, errors, records = [], [], [], {}
    rounds = max((len(j['alternatives']) for j in pending),default=0)
    print(json.dumps(dict(planned_deadlines=len(pending),alternatives=sum(len(j['alternatives']) for j in pending),rounds=rounds)),flush=True)
    for rank in range(rounds):
        selected = [(j,j['alternatives'][rank]) for j in pending if rank<len(j['alternatives'])]
        hours = list(dict.fromkeys(aware(c['committer_at']).strftime('%Y-%m-%d-%H') for _,c in selected))
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures={pool.submit(capture_hour,out,h):h for h in hours if h not in records}
            for future in as_completed(futures):
                h=futures[future]
                try:
                    record=future.result();verify_hour(out,record);records[h]=record
                except Exception as exc:
                    errors.append(dict(round=rank+1,hour=h,error=type(exc).__name__))
        resolved=set()
        for job,c in selected:
            h=aware(c['committer_at']).strftime('%Y-%m-%d-%H')
            if h not in records:
                attempts.append(dict(season=c['season'],gw=c['gw'],path=c['path'],hour=h,status='hour_unavailable'))
                continue
            evidence=witness(c,records[h])
            attempts.append(evidence)
            if evidence['eligible_predeadline']:
                original=job['original']
                found.append(dict(candidate=c,witness=evidence,original_path=original['path'],
                    extra_staleness_hours=(aware(original['source_claimed_at']+'+00:00')-aware(c['source_claimed_at']+'+00:00')).total_seconds()/3600))
                resolved.add((c['season'],c['gw']))
        pending=[j for j in pending if (j['original']['season'],j['original']['gw']) not in resolved]
        checkpoint=dict(completed_round=rank+1,total_rounds=rounds,new_witnesses=len(found),remaining_deadlines=len(pending),acquired_hours=len(records),errors=len(errors))
        (out/'checkpoint.json').write_text(json.dumps(checkpoint,indent=2)+'\n')
        print(json.dumps(checkpoint),flush=True)
        if not pending:break
    artifacts={}
    for name,value in [('found.json',found),('attempts.json',attempts),('unresolved.json',[j['original'] for j in pending])]:
        data=(json.dumps(value,indent=2)+'\n').encode();(out/name).write_bytes(data);artifacts[name]=digest(data)
    report=dict(version='publication-alternatives-v1',plan_sha256=digest(payload),implementation_sha256=digest(Path(__file__).read_bytes()),
        original_candidates=input_plan['original_candidates'],preserved_witnesses=len(input_plan['preserved']),
        searched_deadlines=len(input_plan['jobs']),new_witnesses=len(found),remaining_deadlines=len(pending),
        acquired_hours=len(records),compressed_bytes=sum(r['compressed_bytes'] for r in records.values()),
        artifacts=artifacts,errors=errors,
        hour_report_sha256={h:digest((out/'hours'/(h+'.json')).read_bytes()) for h in sorted(records)},
        training_admitted=False,production_changed=False)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('raw-root','provenance-root','archive-root','out'):
        ap.add_argument('--'+name,type=Path,required=True)
    args=ap.parse_args()
    result=run(args.raw_root,args.provenance_root,args.archive_root,args.out)
    print(json.dumps(result,indent=2))
    if result['errors']:raise SystemExit(1)


if __name__=='__main__':main()
