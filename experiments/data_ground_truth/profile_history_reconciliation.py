"""Reconcile one representative of each distinct archived history against pinned GT."""
from __future__ import annotations
import argparse
from collections import Counter
import io
import json
from pathlib import Path
import pandas as pd
from experiments.data_ground_truth.historical_2014 import OPPONENT_CODES,reconcile_2014
from experiments.data_ground_truth.profile_snapshot_collection import describe_payload
from experiments.data_ground_truth.snapshots import unpack
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked,verify

GT_ID='e0b5ab38c46df8eae793742421965cf80665764cbbf23dfcb99e3c8b50247998'
GT_MANIFEST='9a71bb11bf6ed5351b2084e104b7b4e8e279995d2f3d25cd8a095989af50798e'
FIXTURES={2014:'4f6c42e636040f1910a914e4c7c4d43aa4a81a00af5549daefe62b28345ed51f',
          2015:'7b1c5b8cc70e551413b981a58988fee9205fc7987ec2ba5745c93d8aa69d3a66'}


def resolve(players,fixtures):
    weekly,metadata=unpack(players)
    if weekly.empty:return None,metadata,dict(status='no_history')
    if metadata.code.isna().any() or metadata.code.duplicated().any():raise ValueError('ambiguous representative codes')
    candidates=[];errors={}
    for start,calendar in fixtures.items():
        try:
            labels,quality=reconcile_2014(weekly,metadata.loc[metadata.id.isin(weekly.id)],calendar,season_start=start,
                opponent_codes=OPPONENT_CODES|dict(BOU=91,NOR=45,WAT=57))
            candidates.append((labels,quality))
        except ValueError as error:errors[str(start)]=str(error)
    if len(candidates)!=1:return None,metadata,dict(status='unreconciled' if not candidates else 'ambiguous_season',errors=errors)
    labels,quality=candidates[0]
    labels=labels.merge(metadata[['id','code']],on='id',validate='many_to_one')
    return labels,metadata,dict(status='reconciled',season=labels.season.iloc[0],rows=len(labels),fixtures=quality['fixtures'],
        gameweeks=quality['gameweeks'],total_reconciliation='representative_profile_total_matches_history')


def compare(labels,gt):
    paired=labels.merge(gt,left_on=['id','matchId'],right_on=['element','fixture'],how='left',validate='one_to_one',indicator=True,suffixes=('_src','_gt'))
    both=paired._merge.eq('both');flags={}
    for name,a,b in [('minutes','mins','minutes'),('points','gw_pts','total_points'),('gameweek','gw_src','gw_gt'),('code','code','official_player_code')]:
        flags[name+'_conflict']=both&paired[a].ne(paired[b]);paired[name+'_conflict']=flags[name+'_conflict']
    paired['missing_in_gt']=~both
    bad=paired.loc[(~both)|pd.DataFrame(flags).any(axis=1)].copy()
    cols=['id','matchId','gw_src','mins','gw_pts','code','minutes','total_points','gw_gt','official_player_code','missing_in_gt',*flags]
    report=dict(rows=len(labels),missing_in_gt=int((~both).sum()),**{name:int(values.sum()) for name,values in flags.items()})
    return report,bad[cols]


def build(base,out):
    g100=json.loads(Path(__file__).with_name('results-g100.json').read_text());root=base/'profile-snapshot-audit-g100-v1'
    checked(root/'report.json',g100['report_sha256'])
    entries=json.loads(checked(root/'snapshots.json',g100['audit']['artifacts']['snapshots.json']))
    groups={}
    for e in entries:
        if e['status']=='profile_history_schema_valid':groups.setdefault(e['history_sha256'],[]).append(e)
    fixtures={start:pd.read_csv(io.BytesIO(checked(base/'raw-history-v2/objects'/sha,sha))) for start,sha in FIXTURES.items()}
    package=base/'training-datasets'/GT_ID;checked(package/'manifest.json',GT_MANIFEST);manifest=verify(package)
    gt={p['season']:pd.read_csv(package/p['file']) for p in manifest['partitions'] if p['season'] in {'2014-15','2015-16'}}
    records=[];disagreements=[];coverage={season:set() for season in gt}
    for i,(sha,members) in enumerate(sorted(groups.items()),1):
        chosen=min(members,key=lambda e:e['path']);data=checked(base/'profile-snapshots-g100/objects'/chosen['sha256'],chosen['sha256'])
        actual=describe_payload(data)
        if actual.get('history_sha256')!=sha:raise ValueError('projection changed')
        labels,metadata,quality=resolve(list(json.loads(data).values()),fixtures)
        record=dict(projection_sha256=sha,representative_path=chosen['path'],representative_sha256=chosen['sha256'],member_snapshots=len(members),**quality)
        if labels is not None:
            season=quality['season'];comparison,bad=compare(labels,gt[season]);record['comparison']=comparison
            bad['season']=season;bad['projection_sha256']=sha;disagreements.append(bad)
            coverage[season].update((int(r.id),int(r.matchId)) for r in labels.itertuples())
        records.append(record)
        if i%25==0:print(f'reconciled projections {i}/{len(groups)}',flush=True)
    out.mkdir(parents=True,exist_ok=True)
    (out/'projections.json').write_text(json.dumps(records,indent=2)+'\n')
    bad=pd.concat(disagreements,ignore_index=True) if disagreements else pd.DataFrame()
    bad.to_csv(out/'disagreements.csv',index=False)
    summary={}
    for season,keys in coverage.items():
        baseline={(int(r.element),int(r.fixture)) for r in gt[season].itertuples()}
        summary[season]=dict(unique_player_fixture_keys=len(keys),gt_rows=len(baseline),overlap_keys=len(keys&baseline),missing_gt_keys=len(keys-baseline),gt_keys_without_reconciled_history=len(baseline-keys))
    report=dict(version='profile-history-reconciliation-v1',source_inventory_sha256=g100['audit']['artifacts']['snapshots.json'],
        implementation_sha256=digest(Path(__file__).read_bytes()),gt_dataset_id=GT_ID,gt_manifest_sha256=GT_MANIFEST,fixture_sha256=FIXTURES,
        source_snapshots=len(entries),valid_schema_snapshots=sum(len(v) for v in groups.values()),projections=len(records),
        statuses=dict(Counter(r['status'] for r in records)),coverage=summary,disagreement_rows=len(bad),
        conflict_counts={n:int(bad[n].sum()) for n in ['minutes_conflict','points_conflict','gameweek_conflict','code_conflict','missing_in_gt']} if len(bad) else {},
        training_admitted=False,gt_changed=False,production_changed=False,
        limitations=['one_representative_per_history_projection','mutable_profile_totals_and_codes_not_validated_for_every_member',
                    'fixture_match_does_not_prove_finalized_observation','disagreements_not_automatically_GT_errors',
                    'nominal_capture_times_not_publication_proof'],
        artifacts={n:digest((out/n).read_bytes()) for n in ['projections.json','disagreements.csv']})
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.base,a.out),indent=2))
