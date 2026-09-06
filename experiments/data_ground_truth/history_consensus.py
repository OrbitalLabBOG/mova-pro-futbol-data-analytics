"""Measure pinned history CSV coverage without merging conflicting season outcomes."""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import re

import pandas as pd

from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked

KEYS=['season','official_player_code']


def parse(data: bytes,record: dict):
    columns=['element_code','season_name','minutes','total_points']
    try:frame=pd.read_csv(io.BytesIO(data))
    except pd.errors.EmptyDataError:return pd.DataFrame(), 'empty_file'
    if frame.empty:return pd.DataFrame(), 'empty_history'
    if not set(columns)<=set(frame):raise ValueError('missing historical columns')
    frame=frame[columns].rename(columns={'element_code':'official_player_code','season_name':'season','total_points':'points'}).copy()
    if frame.official_player_code.nunique()!=1:raise ValueError('multiple player codes in history')
    for col in ['official_player_code','minutes','points']:
        values=pd.to_numeric(frame[col],errors='raise')
        if values.isna().any() or not values.mod(1).eq(0).all():raise ValueError('noninteger historical outcome')
        frame[col]=values.astype('int64')
    if frame.official_player_code.le(0).any() or frame.minutes.lt(0).any():raise ValueError('invalid historical value')
    source_year=int(record['path'].split('/')[1][:4])
    for season in frame.season:
        if not isinstance(season,str) or not re.fullmatch(r'[0-9]{4}/[0-9]{2}',season):raise ValueError('invalid season name')
        if (int(season[:4])+1)%100!=int(season[-2:]) or int(season[:4])>source_year:raise ValueError('invalid history season chronology')
    if frame.duplicated(KEYS).any():raise ValueError('duplicate history season')
    frame['source_sha256']=record['sha256'];frame['source_path']=record['path']
    return frame,'parsed'


def consensus(frame: pd.DataFrame):
    counts=frame.groupby(KEYS)[['minutes','points']].nunique()
    bad=counts.gt(1).any(axis=1).rename('conflicting_outcomes').reset_index()
    joined=frame.merge(bad,on=KEYS,validate='many_to_one')
    rejected=joined[joined.conflicting_outcomes].copy()
    accepted=joined[~joined.conflicting_outcomes].groupby(KEYS,as_index=False).agg(
        minutes=('minutes','first'),points=('points','first'),witness_records=('source_sha256','size'),
        distinct_source_blobs=('source_sha256','nunique'))
    accepted['available_at']=None;accepted['eligible_predeadline']=False;accepted['eligible_training']=False
    accepted['observation_unit']='player_season';accepted['population_complete']=False
    return accepted,rejected


def build(root: Path,prior_root: Path,out: Path):
    manifest_bytes=(root/'manifest.json').read_bytes();manifest=json.loads(manifest_bytes)
    if manifest['errors'] or len(manifest['records'])!=manifest['expected_files']:raise ValueError('incomplete history acquisition')
    prior_report=json.loads((prior_root/'report.json').read_text())
    prior=pd.read_csv(io.BytesIO(checked(prior_root/'season_totals.csv',prior_report['season_totals_sha256'])))
    prior=prior[KEYS+['minutes','points','source_sha256']].assign(source_path='archived_2015_16_player_json')
    frames=[];files=[];quarantine=[]
    for record in manifest['records']:
        data=checked(root/'objects'/record['sha256'],record['sha256'])
        try:frame,status=parse(data,record)
        except (ValueError,UnicodeError,pd.errors.ParserError) as exc:
            quarantine.append(dict(path=record['path'],sha256=record['sha256'],error=str(exc)));continue
        files.append(dict(path=record['path'],sha256=record['sha256'],status=status,rows=len(frame)))
        if not frame.empty:frames.append(frame)
    if not frames:raise ValueError('no parsed player histories')
    observations=pd.concat(frames+[prior],ignore_index=True)
    observations['available_at']=None;observations['eligible_predeadline']=False;observations['eligible_training']=False
    accepted,rejected=consensus(observations)
    comparison=accepted.merge(prior[KEYS],on=KEYS,how='left',indicator=True,validate='one_to_one')
    out.mkdir(parents=True,exist_ok=True)
    for name,frame in [('source_observations',observations),('consensus_totals',accepted),('conflicting_observations',rejected)]:
        frame.to_csv(out/(name+'.csv'),index=False)
    (out/'file_audit.json').write_text(json.dumps(dict(files=files,quarantine=quarantine),indent=2)+'\n')
    report=dict(version='history-consensus-v1',acquired_files=len(manifest['records']),
        parsed_nonempty_files=len(frames),empty_files=sum(f['rows']==0 for f in files),quarantined_files=len(quarantine),
        acquired_bytes=sum((root/'objects'/r['sha256']).stat().st_size for r in manifest['records']),
        prior_rows=len(prior),source_observation_rows=len(observations),
        consensus_player_seasons=len(accepted),conflicting_player_seasons=len(rejected[KEYS].drop_duplicates()),
        additional_consensus_keys_over_prior=int(comparison['_merge'].eq('left_only').sum()),
        season_counts={s:len(g) for s,g in accepted.groupby('season')},
        artifacts={name:digest((out/name).read_bytes()) for name in ['source_observations.csv','consensus_totals.csv','conflicting_observations.csv','file_audit.json']},
        manifest_sha256=digest(manifest_bytes),prior_sha256=prior_report['season_totals_sha256'],
        source_independence='repeated_API_archives_not_independent_measurements',
        complete_population_seasons=0,new_complete_gameweek_seasons=0)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for arg in ['root','prior-root','out']:ap.add_argument('--'+arg,type=Path,required=True)
    args=ap.parse_args();print(json.dumps(build(args.root,args.prior_root,args.out),indent=2))


if __name__=='__main__':main()
