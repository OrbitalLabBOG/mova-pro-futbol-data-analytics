"""Complete bounded publication-hour searches up to two unresolved deadlines."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from experiments.data_ground_truth import historical_fixture_publication as historical
from experiments.data_ground_truth import calendar_publication_extension as extension
from experiments.data_ground_truth.bootstrap_time import aware
from experiments.data_ground_truth.raw import digest

TARGETS={('2021-22',32),('2022-23',23)}


def hours(candidate):
    # G35 already checked offsets 0..24. Never infer publication from Git clocks.
    result=[]
    for offset in range(25,49):
        hour=extension.scheduled_hour(candidate,offset)
        if hour is None:break
        result.append(hour)
    if extension.scheduled_hour(candidate,49) is not None:
        raise ValueError('target exceeds reviewed 48 hour search bound')
    return result


def build(base,out,offline=False):
    audit,all_candidates=historical.candidates(base/'fixture-history-audit-v1',base/'raw-fixture-history-v1',base/'fixtures-git-provenance')
    targets=[c for c in all_candidates if (c['season'],c['gw']) in TARGETS]
    if len(targets)!=len(TARGETS):raise ValueError('target population differs')
    plan=[dict(candidate=c,hours=hours(c)) for c in targets]
    scheduled=sorted({h for p in plan for h in p['hours']});records={};errors=[]
    def acquire(hour):
        try:return hour,extension.capture(out,hour,offline),None
        except Exception as exc:return hour,None,type(exc).__name__
    with ThreadPoolExecutor(max_workers=3) as pool:
        for h,r,error in pool.map(acquire,scheduled):
            if error:errors.append(dict(hour=h,error=error))
            else:records[h]=r
            print(json.dumps(dict(hour=h,error=error)),flush=True)
    witnesses=[]
    for p in plan:
        c=p['candidate']
        proofs=[proof for h in p['hours'] if h in records and (proof:=extension.proof(c,records[h],base/'fixtures-git-provenance'))]
        if proofs:witnesses.append(min(proofs,key=lambda r:aware(r['available_at'])))
    out.mkdir(parents=True,exist_ok=True)
    payload=(json.dumps(witnesses,indent=2)+'\n').encode();(out/'witnesses.json').write_bytes(payload)
    report=dict(version='calendar-deadline-tail-v1',fixture_audit_sha256=digest(audit),
        implementation_sha256=digest(Path(__file__).read_bytes()),plan=plan,
        acquired_hours=len(records),downloaded_bytes=sum(r['compressed_bytes'] for r in records.values()),
        errors=errors,resolved=len(witnesses),
        push_events=sum(len(r['push_events']) for r in records.values()),merge_events=sum(len(r['merge_events']) for r in records.values()),
        hour_report_sha256={h:digest((out/'hours'/(h+'.json')).read_bytes()) for h in scheduled if h in records},
        witnesses_sha256=digest(payload),training_admitted=False,production_changed=False,new_FPL_labels=0,
        limitations=['negative_archive_search_is_not_proof_of_nonpublication',
            'only_offsets_25_to_deadline_are_examined_here_prior_search_remains_separate',
            'compressed_source_hash_retained_relevant_events_retained_unrelated_activity_discarded',
            'publication_witness_is_not_API_capture_time'])
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base-root',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--offline',action='store_true')
    a=p.parse_args();r=build(a.base_root,a.out,a.offline);print(json.dumps({k:v for k,v in r.items() if k not in ('plan','hour_report_sha256')}))
    if r['errors']:raise SystemExit(1)


if __name__=='__main__':main()
