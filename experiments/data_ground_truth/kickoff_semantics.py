"""Compare retrospective label clocks with versioned fixtures without overwriting either."""
from __future__ import annotations
import argparse
from collections import Counter
import gzip
import io
import json
from pathlib import Path
import pandas as pd
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked, verify
from experiments.data_ground_truth.bootstrap_time import aware


def compare(rows, fixtures):
    lookup={r['id']:r for r in fixtures}
    if len(lookup)!=len(fixtures):raise ValueError('duplicate fixture identity')
    differences=[];counts=Counter()
    for row in rows:
        ref=lookup.get(int(row['fixture']))
        if ref is None:counts['missing_reference']+=1;continue
        left=row['event_time_utc'];right=ref['kickoff_time']
        if pd.isna(left) or not right:counts['unknown_time']+=1;continue
        counts['compared_rows']+=1
        if aware(left)!=aware(right):
            differences.append(dict(element=int(row['element']),fixture=int(row['fixture']),label_time=left,
                reference_time=right,delta_seconds=int((aware(right)-aware(left)).total_seconds())))
        if int(row['gw'])!=ref['event']:counts['gameweek_disagreements']+=1
    return dict(counts),differences


def build(package:Path,fixture_root:Path,out:Path):
    manifest=verify(package)
    report_bytes=(fixture_root/'report.json').read_bytes();report=json.loads(report_bytes)
    versions=json.loads(checked(fixture_root/'versions.json',report['artifacts']['versions.json']))
    seasons=[];differences=[];timelines=[]
    for part in manifest['partitions']:
        season=part['season'];history=sorted([v for v in versions if v['season']==season],key=lambda v:(v['committer_at'],v['revision']))
        if not history:
            seasons.append(dict(season=season,status='no_fixture_history',rows=part['rows']));continue
        last=history[-1]
        fixtures=json.loads(gzip.decompress(checked(fixture_root/'objects'/last['normalized_sha256'],last['normalized_sha256'])))
        frame=pd.read_csv(io.BytesIO(gzip.decompress(checked(package/part['file'],part['sha256']))))
        counts,delta=compare(frame.to_dict('records'),fixtures)
        ids={r['fixture'] for r in delta}
        seasons.append(dict(season=season,status='compared',rows=part['rows'],reference_revision=last['revision'],
            reference_sha256=last['normalized_sha256'],discrepant_rows=len(delta),discrepant_fixtures=len(ids),**counts))
        differences.extend(dict(season=season,**r) for r in delta)
        for version in history:
            data=json.loads(gzip.decompress(checked(fixture_root/'objects'/version['normalized_sha256'],version['normalized_sha256'])))
            for r in data:
                if r['id'] in ids:timelines.append(dict(season=season,revision=version['revision'],committer_at=version['committer_at'],
                    source_sha256=version['source_sha256'],normalized_sha256=version['normalized_sha256'],fixture=r))
    out.mkdir(parents=True,exist_ok=True);artifacts={}
    for name,data in [('differences.json',differences),('fixture_timelines.json',timelines)]:
        payload=(json.dumps(data,indent=2)+'\n').encode();(out/name).write_bytes(payload);artifacts[name]=digest(payload)
    result=dict(version='kickoff-semantics-v1',dataset_id=manifest['dataset_id'],fixture_report_sha256=digest(report_bytes),
        implementation_sha256=digest(Path(__file__).read_bytes()),seasons=seasons,discrepant_rows=len(differences),
        discrepant_season_fixtures=len({(r['season'],r['fixture']) for r in differences}),artifacts=artifacts,
        gt_changed=False,production_changed=False,eligible_predeadline=False,
        limitations=['final_fixture_clock_is_retrospective_not_predeadline_input','Git_time_is_not_publication_proof',
        'scheduled_and_updated_kickoffs_may_both_be_correct_at_different_times','no_automatic_timestamp_repair'])
    (out/'report.json').write_text(json.dumps(result,indent=2)+'\n');return result


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for arg in ('package','fixture-root','out'):ap.add_argument('--'+arg,type=Path,required=True)
    a=ap.parse_args();print(json.dumps(build(a.package,a.fixture_root,a.out),indent=2))


if __name__=='__main__':main()
