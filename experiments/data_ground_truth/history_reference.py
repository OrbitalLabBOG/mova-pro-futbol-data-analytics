"""Contrast historical season totals against validated gameweek-label sums."""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

import pandas as pd

from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked,verify

KEYS=['season','official_player_code']


def compare(totals: pd.DataFrame,reference: pd.DataFrame):
    if totals.duplicated(KEYS).any() or reference.duplicated(KEYS).any():raise ValueError('ambiguous season totals')
    supported=totals[totals.season.isin(reference.season.unique())]
    joined=supported.merge(reference,on=KEYS,how='outer',suffixes=('','_reference'),indicator=True,validate='one_to_one')
    both=joined['_merge'].eq('both')
    joined['outcome_disagreement']=both & (joined.minutes.ne(joined.minutes_reference)|joined.points.ne(joined.points_reference))
    seasons={}
    for season,group in joined.groupby('season'):
        seasons[season]=dict(matched_players=int(group['_merge'].eq('both').sum()),
            outcome_disagreements=int(group.outcome_disagreement.sum()),
            history_without_reference=int(group['_merge'].eq('left_only').sum()),
            reference_without_history=int(group['_merge'].eq('right_only').sum()))
    return joined,dict(seasons=seasons,matched_players=int(both.sum()),
        outcome_disagreements=int(joined.outcome_disagreement.sum()),
        unsupported_history_rows=len(totals)-len(supported),
        status='retrospective_totals_comparison_not_population_completion')


def build(consensus_root: Path,labels_root: Path | None,out: Path,package: Path | None=None):
    report=json.loads((consensus_root/'report.json').read_text())
    sha=report['artifacts']['consensus_totals.csv']
    totals=pd.read_csv(io.BytesIO(checked(consensus_root/'consensus_totals.csv',sha)))
    frames=[];hashes={};package_id=None
    if package is not None:
        manifest=verify(package);package_id=manifest['dataset_id']
        for entry in manifest['partitions']:
            frame=pd.read_csv(package/entry['file'],compression='gzip')
            grouped=frame.groupby('official_player_code',as_index=False).agg(minutes=('minutes','sum'),points=('total_points','sum'))
            grouped['season']=entry['season'].replace('-','/');frames.append(grouped);hashes[entry['season']]=entry['sha256']
    else:
        if labels_root is None:raise ValueError('reference root or package required')
        manifest=json.loads((labels_root/'labels-manifest.json').read_text())
        for season,info in sorted(manifest['seasons'].items()):
            frame=pd.read_csv(io.BytesIO(checked(labels_root/'labels'/(season+'.csv'),info['artifact_sha256'])),low_memory=False)
            grouped=frame.groupby('official_player_code',as_index=False).agg(minutes=('minutes','sum'),points=('total_points','sum'))
            grouped['season']=season.replace('-','/');frames.append(grouped);hashes[season]=info['artifact_sha256']
    joined,quality=compare(totals,pd.concat(frames,ignore_index=True))
    out.mkdir(parents=True,exist_ok=True);joined.to_csv(out/'comparison.csv',index=False)
    quality.update(version='history-reference-v1',history_sha256=sha,reference_sha256=hashes,
        reference_dataset_id=package_id,reference_scope='rows_with_official_player_identity',
        comparison_sha256=digest((out/'comparison.csv').read_bytes()))
    (out/'report.json').write_text(json.dumps(quality,indent=2)+'\n');return quality


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for arg in ['consensus-root','out']:ap.add_argument('--'+arg,type=Path,required=True)
    group=ap.add_mutually_exclusive_group(required=True)
    group.add_argument('--labels-root',type=Path);group.add_argument('--package',type=Path)
    args=ap.parse_args();print(json.dumps(build(args.consensus_root,args.labels_root,args.out,args.package),indent=2))


if __name__=='__main__':main()
