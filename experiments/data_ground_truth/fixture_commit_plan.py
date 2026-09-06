"""Export complete source trees at nominal predeadline commits; never splice files by date."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess

from experiments.data_ground_truth.bootstrap_time import aware
from experiments.data_ground_truth.fixture_complement import SOURCES,select
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked


def git(repo,*args):return subprocess.run(['git','-C',str(repo),*args],check=True,capture_output=True,text=True).stdout.strip()


def tree(repo,revision,source):
    import re
    config=SOURCES[source];entries=[]
    output=git(repo,'ls-tree','-r',revision,'--','data/2025-2026/By Tournament/Premier League/' if source=='core' else 'data/2025/csv/fixtures.csv')
    for line in output.splitlines():
        metadata,path=line.split('\t',1);mode,kind,sha=metadata.split()
        if re.fullmatch(config['pattern'],path):
            if kind!='blob' or mode!='100644':raise ValueError('unexpected fixture tree entry')
            entries.append(dict(path=path,git_blob=sha))
    return sorted(entries,key=lambda e:e['path'])


def build(repo:Path,source:str,log:Path,selection_root:Path,out:Path):
    if git(repo,'rev-parse','--is-shallow-repository')!='false':raise ValueError('shallow source Git history')
    config=SOURCES[source]
    if git(repo,'cat-file','-t',config['revision'])!='commit':raise ValueError('missing source pin')
    log_bytes=log.read_bytes();versions,_=select(log_bytes,source)
    selection_bytes=(selection_root/'report.json').read_bytes();selection=json.loads(selection_bytes)
    candidates=json.loads(checked(selection_root/'nominal_deadline_candidates.json',selection['artifacts']['nominal_deadline_candidates.json']))
    rows=[];trees={}
    for c in candidates:
        if c['season']!='2025-26':continue
        choices=[v for v in versions if aware(v['committer_at'])<aware(c['deadline'])]
        row=dict(season=c['season'],gw=c['gw'],deadline=c['deadline'],available_at=None,eligible_predeadline=False)
        if not choices:row['status']='no_prior_commit';rows.append(row);continue
        v=max(choices,key=lambda v:(aware(v['committer_at']),v['commit']));revision=v['commit']
        # Require the chosen commit to be reachable from the declared pin.
        subprocess.run(['git','-C',str(repo),'merge-base','--is-ancestor',revision,config['revision']],check=True,capture_output=True)
        if revision not in trees:trees[revision]=tree(repo,revision,source)
        row.update(revision=revision,source_committer_at=v['committer_at'],entries=trees[revision],
            nominal_commit_age_hours=(aware(c['deadline'])-aware(v['committer_at'])).total_seconds()/3600,
            status='source_tree_exported')
        rows.append(row)
    out.mkdir(parents=True,exist_ok=True);data=(json.dumps(rows,indent=2)+'\n').encode();(out/'trees.json').write_bytes(data)
    ages=[r['nominal_commit_age_hours'] for r in rows if 'nominal_commit_age_hours' in r]
    report=dict(version='fixture-commit-plan-v1',source=source,repository=config['repository'],pinned_revision=config['revision'],
        git_log_sha256=digest(log_bytes),selection_report_sha256=digest(selection_bytes),implementation_sha256=digest(Path(__file__).read_bytes()),
        trees_sha256=digest(data),deadlines=len(rows),with_prior_commit=len(ages),distinct_commits=len(trees),
        within_48h=sum(a<=48 for a in ages),max_nominal_commit_age_hours=max(ages) if ages else None,
        file_counts=sorted({len(r['entries']) for r in rows if 'entries' in r}),
        eligible_predeadline=False,production_changed=False,limitation='complete_Git_tree_is_not_proof_of_latest_official_calendar_or_historical_publication')
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--source',choices=sorted(SOURCES),required=True)
    for name in ('repo','log','selection-root','out'):ap.add_argument('--'+name,type=Path,required=True)
    a=ap.parse_args();print(json.dumps(build(a.repo,a.source,a.log,a.selection_root,a.out),indent=2))


if __name__=='__main__':main()
