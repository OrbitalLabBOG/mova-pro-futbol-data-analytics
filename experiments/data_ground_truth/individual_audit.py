"""Compare every archived individual gameweek CSV with a verified label package."""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

import pandas as pd

from experiments.data_ground_truth.training_dataset import COMPONENTS,checked,quarantine_postponed,verify
from experiments.data_ground_truth.raw import digest


def compare_player(individual,reference,metadata,fixtures):
    if individual.empty:return dict(status='empty_history',rows=0),[]
    individual=individual.copy();individual['gw']=individual['round']
    exact_duplicates=int(individual.duplicated().sum());individual=individual.drop_duplicates()
    removed=0
    if individual.duplicated(['element','fixture']).any():
        individual,q=quarantine_postponed(individual,fixtures);removed=len(q)
    if individual.element.nunique()!=1:raise ValueError('mixed player identities')
    element=int(individual.iloc[0].element);meta=metadata[metadata.id.eq(element)]
    if len(meta)!=1:raise ValueError('unknown player metadata')
    meta=meta.iloc[0];old=reference[reference.element.eq(element)]
    if not old.official_player_code.eq(meta.code).all():raise ValueError('official identity disagreement')
    columns=['minutes','total_points']+COMPONENTS
    joined=old[['element','fixture','gw','event_time_utc']+columns].merge(
        individual[['element','fixture','gw','kickoff_time']+columns],on=['element','fixture'],how='outer',
        suffixes=('_reference','_individual'),indicator=True,validate='one_to_one')
    both=joined['_merge'].eq('both');differences=[]
    for column in columns:
        left=joined[column+'_reference'];right=joined[column+'_individual']
        different=both & ~(left.eq(right)|(left.isna() & right.isna()))
        for row in joined.loc[different].to_dict('records'):
            differences.append(dict(element=element,official_player_code=int(meta.code),fixture=int(row['fixture']),field=column,
                reference=row[column+'_reference'],individual=row[column+'_individual']))
    totals=[]
    for column in columns:
        value=individual[column].sum(min_count=1)
        if column not in meta or pd.isna(value) or pd.isna(meta[column]) or value!=meta[column]:totals.append(column)
    event_mismatch=(pd.to_datetime(joined.event_time_utc,utc=True).ne(pd.to_datetime(joined.kickoff_time,utc=True))) & both
    return dict(status='compared',element=element,official_player_code=int(meta.code),entity_type=int(meta.element_type),
        rows=len(individual),exact_duplicates=exact_duplicates,postponed_rows_removed=removed,
        reference_only_rows=int(joined['_merge'].eq('left_only').sum()),individual_only_rows=int(joined['_merge'].eq('right_only').sum()),
        gameweek_disagreements=int((both & joined.gw_reference.ne(joined.gw_individual)).sum()),
        kickoff_disagreements=int(event_mismatch.sum()),changed_fields=len(differences),
        changed_rows=len({d['fixture'] for d in differences}),season_total_disagreements=totals),differences


def build(root: Path,recent_root: Path,package: Path,out: Path):
    source_bytes=(root/'manifest.json').read_bytes();manifest=json.loads(source_bytes)
    if manifest['errors'] or len(manifest['records'])!=manifest['expected_files']:raise ValueError('incomplete individual acquisition')
    package_manifest=verify(package);refs={p['season']:pd.read_csv(package/p['file'],compression='gzip') for p in package_manifest['partitions']}
    raw=json.loads((recent_root/'manifest.json').read_text())['records'];metadata={};fixtures={};input_hashes={}
    for record in raw:
        if record['repository']!='vaastav/Fantasy-Premier-League':continue
        name=Path(record['path']).name
        if name not in {'players_raw.csv','fixtures.csv'}:continue
        season=record['path'].split('/')[1];data=checked(recent_root/'objects'/record['sha256'],record['sha256'])
        (metadata if name=='players_raw.csv' else fixtures)[season]=pd.read_csv(io.BytesIO(data))
        input_hashes[record['path']]=record['sha256']
    files=[];errors=[];differences=[]
    for i,record in enumerate(manifest['records'],1):
        season=record['path'].split('/')[1]
        try:
            data=checked(root/'objects'/record['sha256'],record['sha256'])
            try:individual=pd.read_csv(io.BytesIO(data))
            except pd.errors.EmptyDataError:individual=pd.DataFrame()
            quality,delta=compare_player(individual,refs[season],metadata[season],fixtures.get(season,pd.DataFrame()))
            files.append(dict(path=record['path'],sha256=record['sha256'],season=season,**quality))
            differences.extend(dict(season=season,path=record['path'],source_sha256=record['sha256'],**d) for d in delta)
        except (ValueError,KeyError,UnicodeError,pd.errors.ParserError) as exc:
            errors.append(dict(path=record['path'],sha256=record['sha256'],error=str(exc)))
        if i%1000==0:print(json.dumps(dict(audited=i,errors=len(errors))),flush=True)
    seasons={}
    for season in sorted({r['season'] for r in files}):
        subset=[r for r in files if r['season']==season];compared=[r for r in subset if r['status']=='compared']
        seen={r['element'] for r in compared}
        seasons[season]=dict(files=len(subset),empty_files=sum(r['status']=='empty_history' for r in subset),
            rows=sum(r['rows'] for r in subset),changed_fields=sum(r['changed_fields'] for r in compared),
            changed_rows=sum(r['changed_rows'] for r in compared),
            players_with_season_total_disagreements=sum(bool(r['season_total_disagreements']) for r in compared),
            reference_players_without_compared_file=len(set(refs[season].element)-seen),
            manager_files=sum(r['entity_type']==5 for r in compared),
            reference_only_rows=sum(r['reference_only_rows'] for r in compared),individual_only_rows=sum(r['individual_only_rows'] for r in compared),
            kickoff_disagreements=sum(r['kickoff_disagreements'] for r in compared),gameweek_disagreements=sum(r['gameweek_disagreements'] for r in compared))
    out.mkdir(parents=True,exist_ok=True)
    for name,value in [('file_audit',dict(files=files,errors=errors)),('differences',differences)]:
        (out/(name+'.json')).write_text(json.dumps(value,indent=2)+'\n')
    report=dict(version='individual-gameweek-audit-v1',source_manifest_sha256=digest(source_bytes),reference_dataset_id=package_manifest['dataset_id'],
        input_sha256=input_hashes,files=len(manifest['records']),errors=len(errors),seasons=seasons,
        changed_fields=len(differences),artifacts={name:digest((out/(name+'.json')).read_bytes()) for name in ['file_audit','differences']})
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for arg in ['root','recent-root','package','out']:ap.add_argument('--'+arg,type=Path,required=True)
    args=ap.parse_args();r=build(args.root,args.recent_root,args.package,args.out);print(json.dumps(r,indent=2))


if __name__=='__main__':main()
