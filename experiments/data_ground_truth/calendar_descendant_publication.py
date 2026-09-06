"""Target archive hours using verified descendant Git clocks; clocks alone prove no publication."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
from pathlib import Path
import subprocess
from experiments.data_ground_truth import calendar_publication_extension as extension
from experiments.data_ground_truth import historical_fixture_publication as historical
from experiments.data_ground_truth.bootstrap_time import aware
from experiments.data_ground_truth.fixture_commit_plan import git
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked


def descendant_hours(candidate,commits,repo):
    hours=set()
    for sha,time in commits:
        if sha==candidate['commit'] or not aware(candidate['committer_at'])<=aware(time)<aware(candidate['deadline']):continue
        try:git(repo,'merge-base','--is-ancestor',candidate['commit'],sha)
        except subprocess.CalledProcessError:continue
        start=aware(time).replace(minute=0,second=0,microsecond=0)
        for offset in (0,1):
            t=start+timedelta(hours=offset)
            if t<aware(candidate['deadline']):hours.add(t.strftime('%Y-%m-%d-%H'))
    return sorted(hours)


def build(base,out,offline=False):
    parent_bytes=(base/'calendar-carryforward-v2/report.json').read_bytes();parent=json.loads(parent_bytes)
    audit,cs=historical.candidates(base/'fixture-history-audit-v1',base/'raw-fixture-history-v1',base/'fixtures-git-provenance')
    missing={(r['season'],r['gw']) for r in parent['missing']};targets=[c for c in cs if (c['season'],c['gw']) in missing]
    raw=json.loads(checked(base/'raw-fixture-history-v1/manifest.json',json.loads(audit)['manifest_sha256']))
    log=git(base/'fixtures-git-provenance','log','--format=%H%x09%cI',raw['pinned_revision'])
    commits=[line.split('\t') for line in log.splitlines()]
    plan=[dict(season=c['season'],gw=c['gw'],hours=descendant_hours(c,commits,base/'fixtures-git-provenance')) for c in targets]
    hours=sorted({h for r in plan for h in r['hours']});records={};errors=[]
    def acquire(h):
        try:return h,extension.capture(out,h,offline),None
        except Exception as exc:return h,None,type(exc).__name__
    with ThreadPoolExecutor(max_workers=4) as pool:
        for h,record,error in pool.map(acquire,hours):
            if error:errors.append(dict(hour=h,error=error))
            else:records[h]=record
    selected=[]
    for c,p in zip(targets,plan):
        proofs=[r for h in p['hours'] if h in records and (r:=extension.proof(c,records[h],base/'fixtures-git-provenance'))]
        if proofs:selected.append(dict(min(proofs,key=lambda r:aware(r['available_at'])),normalized_sha256=c['normalized_sha256'],source_committer_at=c['committer_at']))
    out.mkdir(parents=True,exist_ok=True);payload=(json.dumps(selected,indent=2)+'\n').encode();(out/'witnesses.json').write_bytes(payload)
    result=dict(version='calendar-descendant-publication-v1',parent_report_sha256=digest(parent_bytes),fixture_audit_sha256=digest(audit),
                implementation_sha256=digest(Path(__file__).read_bytes()),git_log_sha256=digest(log.encode()),plan=plan,
                targets=len(targets),resolved=len(selected),acquired_hours=len(records),downloaded_bytes=sum(r['compressed_bytes'] for r in records.values()),
                errors=errors,hour_report_sha256={h:digest((out/'hours'/(h+'.json')).read_bytes()) for h in sorted(records)},witnesses_sha256=digest(payload),
                production_changed=False,training_admitted=False,limitations=['Git_clock_guides_search_only','archive_hours_can_overlap_other_acquisitions'])
    (out/'report.json').write_text(json.dumps(result,indent=2)+'\n');return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base-root',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--offline',action='store_true')
    a=p.parse_args();r=build(a.base_root,a.out,a.offline);print(json.dumps(r,indent=2))
    if r['errors']:raise SystemExit(1)


if __name__=='__main__':main()
