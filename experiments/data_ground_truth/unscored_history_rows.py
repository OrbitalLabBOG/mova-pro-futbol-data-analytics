"""Map scoreless historical rows without inventing scores or finalized outcomes."""
from __future__ import annotations
import argparse
from collections import Counter
import io
import json
from pathlib import Path
import pandas as pd
from experiments.data_ground_truth.historical_2014 import OPPONENT_CODES
from experiments.data_ground_truth.profile_history_reconciliation import FIXTURES,GT_ID,GT_MANIFEST,compare
from experiments.data_ground_truth.profile_snapshot_collection import describe_payload
from experiments.data_ground_truth.snapshots import unpack
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked,verify


def map_rows(weekly,metadata,fixtures,start):
    frame=weekly.copy()
    parts=frame.opp.str.extract(r'^(?P<opponent>[A-Z]{3})\((?P<venue>[HA])\)(?: (?P<own_score>\d+)-(?P<opponent_score>\d+))?\s*$')
    if parts[['opponent','venue']].isna().any().any():raise ValueError('unsupported opponent syntax')
    frame['source_score_present']=parts.own_score.notna()
    frame['source_own_score']=pd.to_numeric(parts.own_score).astype('Int64')
    frame['source_opponent_score']=pd.to_numeric(parts.opponent_score).astype('Int64')
    frame['opponent_code']=parts.opponent.map(OPPONENT_CODES|dict(BOU=91,NOR=45,WAT=57))
    if frame.opponent_code.isna().any():raise ValueError('unknown opponent')
    frame['was_home']=parts.venue.eq('H')
    dates=pd.to_datetime('2000 '+frame.date,format='%Y %d %b %H:%M',errors='raise')
    frame['match_local_time']=[d.replace(year=start if d.month>=7 else start+1).isoformat() for d in dates]
    views=[]
    for home in (True,False):
        views.append(pd.DataFrame(dict(matchId=fixtures.matchId,match_local_time=pd.to_datetime(fixtures.kickoff).map(lambda x:x.isoformat()),
            opponent_code=fixtures['away_team_id' if home else 'home_team_id'],was_home=home)))
    lookup=pd.concat(views,ignore_index=True);keys=['match_local_time','opponent_code','was_home']
    if lookup.duplicated(keys).any():raise ValueError('ambiguous fixture lookup')
    frame=frame.merge(lookup,on=keys,how='left',validate='many_to_one')
    if frame.matchId.isna().any():raise ValueError('unresolved fixtures')
    if frame.duplicated(['id','matchId']).any():raise ValueError('duplicate observation key')
    for name in ('mins','gw_pts','gw'):
        numeric=pd.to_numeric(frame[name],errors='raise')
        if numeric.isna().any() or numeric.ne(numeric.round()).any():raise ValueError('invalid integral observation')
    if not frame.mins.between(0,90).all():raise ValueError('invalid minutes')
    totals=frame.groupby('id').gw_pts.sum().rename('history_total')
    joined=metadata.loc[metadata.id.isin(frame.id),['id','pts']].merge(totals,on='id',validate='one_to_one')
    if joined.pts.ne(joined.history_total).any():raise ValueError('profile total mismatch')
    if metadata.code.isna().any() or metadata.code.duplicated().any():raise ValueError('ambiguous source code')
    frame=frame.merge(metadata[['id','code']],on='id',validate='many_to_one')
    frame['season']=f'{start}-{str(start+1)[-2:]}'
    frame['final_observation_proven']=False
    return frame


def build(base,out):
    prior=json.loads(Path(__file__).with_name('results-g101.json').read_text());root=base/'profile-history-audit-g101-v1'
    checked(root/'report.json',prior['report_sha256'])
    projections=json.loads(checked(root/'projections.json',prior['audit']['artifacts']['projections.json']))
    selected=[p for p in projections if p['status']=='unreconciled']
    fixtures={y:pd.read_csv(io.BytesIO(checked(base/'raw-history-v2/objects'/sha,sha))) for y,sha in FIXTURES.items()}
    package=base/'training-datasets'/GT_ID;checked(package/'manifest.json',GT_MANIFEST);manifest=verify(package)
    gt={p['season']:pd.read_csv(package/p['file']) for p in manifest['partitions'] if p['season'] in {'2014-15','2015-16'}}
    entries=[];scoreless=[];badrows=[];coverage={s:set() for s in gt};out.mkdir(parents=True,exist_ok=True)
    for i,p in enumerate(selected,1):
        data=checked(base/'profile-snapshots-g100/objects'/p['representative_sha256'],p['representative_sha256'])
        if describe_payload(data).get('history_sha256')!=p['projection_sha256']:raise ValueError('projection mismatch')
        weekly,metadata=unpack(list(json.loads(data).values()));candidates=[];errors={}
        for start,calendar in fixtures.items():
            try:candidates.append(map_rows(weekly,metadata,calendar,start))
            except ValueError as error:errors[str(start)]=str(error)
        entry={k:p[k] for k in ['projection_sha256','representative_path','representative_sha256','member_snapshots']}
        if len(candidates)!=1:
            entries.append(entry|dict(status='unmapped' if not candidates else 'ambiguous',errors=errors));continue
        frame=candidates[0];season=frame.season.iloc[0];absent=frame.loc[~frame.source_score_present].copy()
        comparison,bad=compare(frame,gt[season]);entry.update(status='mapped_not_finalized',season=season,rows=len(frame),scoreless_rows=len(absent),
            scoreless_zero_minutes_points=int((absent.mins.eq(0)&absent.gw_pts.eq(0)).sum()),comparison=comparison)
        absent['projection_sha256']=p['projection_sha256'];bad['projection_sha256']=p['projection_sha256'];bad['season']=season
        bad=bad.merge(frame[['id','matchId','source_score_present']],on=['id','matchId'],validate='one_to_one')
        scoreless.append(absent[['season','id','matchId','date','gw','opp','mins','gw_pts','source_score_present','source_own_score','source_opponent_score','final_observation_proven','projection_sha256']]);badrows.append(bad)
        coverage[season].update((int(r.id),int(r.matchId)) for r in frame.itertuples());entries.append(entry)
        if i%25==0:print(f'mapped {i}/{len(selected)} projections',flush=True)
    absent=pd.concat(scoreless,ignore_index=True) if scoreless else pd.DataFrame();bad=pd.concat(badrows,ignore_index=True) if badrows else pd.DataFrame()
    absent.to_csv(out/'scoreless_rows.csv',index=False);bad.to_csv(out/'disagreements.csv',index=False)
    (out/'projections.json').write_text(json.dumps(entries,indent=2)+'\n')
    summary={}
    for season,keys in coverage.items():
        known={(int(r.element),int(r.fixture)) for r in gt[season].itertuples()}
        summary[season]=dict(mapped_keys=len(keys),overlap_keys=len(keys&known),missing_gt_keys=len(keys-known))
    report=dict(version='unscored-history-rows-v1',parent_report_sha256=prior['report_sha256'],implementation_sha256=digest(Path(__file__).read_bytes()),
        gt_dataset_id=GT_ID,gt_manifest_sha256=GT_MANIFEST,fixture_sha256=FIXTURES,projections=len(entries),statuses=dict(Counter(e['status'] for e in entries)),
        scoreless_rows=len(absent),scoreless_unique_keys=len(absent[['season','id','matchId']].drop_duplicates()) if len(absent) else 0,
        scoreless_nonzero_minutes_or_points=int((absent.mins.ne(0)|absent.gw_pts.ne(0)).sum()) if len(absent) else 0,
        coverage=summary,disagreement_rows=len(bad),
        conflict_counts={n:int(bad[n].sum()) for n in ['minutes_conflict','points_conflict','gameweek_conflict','code_conflict','missing_in_gt']} if len(bad) else {},
        finalized_labels_admitted=0,training_admitted=False,gt_changed=False,production_changed=False,
        limitations=['missing_score_not_proof_of_nonappearance','present_score_not_proof_of_finalization','one_representative_per_history_projection',
                    'fixture_mapping_does_not_establish_historic_publication','snapshot_observations_are_repeated_states'],
        artifacts={n:digest((out/n).read_bytes()) for n in ['projections.json','scoreless_rows.csv','disagreements.csv']})
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.base,a.out),indent=2))
