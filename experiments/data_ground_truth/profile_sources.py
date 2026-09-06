"""Reconcile recovered 2014/15 profiles and produce scoped identity candidates."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import pandas as pd
from experiments.data_ground_truth.historical_2014 import reconcile_2014
from experiments.data_ground_truth.snapshots import unpack
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked, verify

FIXTURE_SHA='4f6c42e636040f1910a914e4c7c4d43aa4a81a00af5549daefe62b28345ed51f'
PINS={'nori/hbv401g-2015v-f1a':'f66d0890f73c1a85e28d4560f1cbaeddb7cd083e',
      'llimllib/fantasypl_stats':'db590f1925289069d171dc9766928cdd14817833'}


def compare(labels, metadata, gt):
    if metadata.code.isna().any() or metadata.code.duplicated().any() or metadata.id.duplicated().any():
        raise ValueError('ambiguous source identity')
    paired=labels.merge(metadata[['id','code']],on='id',validate='many_to_one').merge(
        gt,left_on=['id','matchId'],right_on=['element','fixture'],how='left',validate='one_to_one',indicator=True,suffixes=('_src','_gt'))
    if paired._merge.ne('both').any():raise ValueError('source observations missing in GT')
    for a,b in [('mins','minutes'),('gw_pts','total_points'),('gw_src','gw_gt')]:
        if paired[a].ne(paired[b]).any():raise ValueError('observed label disagreement')
    known=paired.official_player_code.notna()
    if paired.loc[known,'code'].ne(paired.loc[known,'official_player_code']).any():raise ValueError('known identity conflict')
    candidates=paired.loc[~known,['id','code']].drop_duplicates().rename(columns={'id':'element','code':'candidate_official_player_code'})
    return candidates,dict(overlap_rows=len(paired),new_match_labels=0,minutes_conflicts=0,points_conflicts=0,gameweek_conflicts=0,
        known_identity_conflicts=0,candidate_identity_players=len(candidates),candidate_identity_rows=int((~known).sum()))


def build(base,out):
    root=base/'profile-source-g98';manifest_raw=(root/'manifest.json').read_bytes();records=json.loads(manifest_raw)['records']
    if len({r['url'] for r in records})!=len(records):raise ValueError('duplicate source receipt')
    groups={};sources={}
    for r in records:
        if PINS.get(r['repository'])!=r['revision']:raise ValueError('unexpected source pin')
        data=checked(root/'objects'/r['sha256'],r['sha256'])
        if len(data)!=r['bytes']:raise ValueError('source size mismatch')
        if r['path'] in {'README.md','cache/teams.json'}:continue
        obj=json.loads(data)
        if r['repository'].startswith('nori/'):
            key='nori_profiles';players=[obj]
        else:
            key=r['path'].replace('/','_').replace('.json','')
            if not isinstance(obj,dict) or any(str(p['id'])!=k for k,p in obj.items()):raise ValueError('profile dictionary identity mismatch')
            players=list(obj.values())
        groups.setdefault(key,[]).extend(players);sources.setdefault(key,[]).append(r['sha256'])
    fixtures=pd.read_csv(base/'raw-history-v2/objects'/FIXTURE_SHA);checked(base/'raw-history-v2/objects'/FIXTURE_SHA,FIXTURE_SHA)
    pointer=dict(dataset_id='d4baf849fb4a051be103f8c469e61a4753edb0b4004f980a000fe5c86ef573db',manifest_sha256='dfedf1d67e1432149704f07f788df3fef1f6f68e752603404ebffe4769289ccf');package=base/'training-datasets'/pointer['dataset_id']
    checked(package/'manifest.json',pointer['manifest_sha256']);gt_manifest=verify(package)
    part=next(p for p in gt_manifest['partitions'] if p['season']=='2014-15');gt=pd.read_csv(package/part['file'])
    entries=[];candidates=[];out.mkdir(parents=True,exist_ok=True);names=[]
    for key,players in sorted(groups.items()):
        annual={h[0] for p in players for h in p['season_history']}
        if '2013/14' not in annual or max(annual) not in {'2013/14','2014/15'}:raise ValueError('unsupported season evidence')
        weekly,metadata=unpack(players)
        labels,quality=reconcile_2014(weekly,metadata.loc[metadata.id.isin(weekly.id)],fixtures)
        candidate,comparison=compare(labels,metadata,gt);candidate['source_group']=key;candidates.append(candidate)
        labels=labels.merge(metadata[['id','code','name']],on='id',validate='many_to_one')
        filename=key+'-labels.csv';labels.to_csv(out/filename,index=False);names.append(filename)
        entries.append(dict(source_group=key,source_contents=sources[key],profiles=len(players),rows=len(labels),
            fixtures=quality['fixtures'],gameweeks=quality['gameweeks'],snapshot_total_disagreements=quality['season_points_disagreements'],
            comparison=comparison,available_at=None,eligible_predeadline=False))
    candidates=pd.concat(candidates,ignore_index=True)
    if candidates.groupby('element').candidate_official_player_code.nunique().gt(1).any():raise ValueError('cross-source candidate conflict')
    identities=candidates[['element','candidate_official_player_code']].drop_duplicates()
    if identities.candidate_official_player_code.duplicated().any():raise ValueError('candidate identity collision')
    known_codes=set(gt.official_player_code.dropna())
    if set(identities.candidate_official_player_code)&known_codes:raise ValueError('candidate collides with known GT identity')
    candidates.to_csv(out/'identity_candidates.csv',index=False);names.append('identity_candidates.csv')
    report=dict(version='profile-sources-v1',manifest_sha256=digest(manifest_raw),fixture_sha256=FIXTURE_SHA,
        implementation_sha256=digest(Path(__file__).read_bytes()),gt_dataset_id=gt_manifest['dataset_id'],
        captured_files=len(records),captured_bytes=sum(r['bytes'] for r in records),groups=entries,
        candidate_players=len(identities),candidate_gt_rows=int(gt.element.isin(identities.element).sum()),
        new_complete_seasons=0,new_match_labels=0,identity_promotion_applied=False,production_changed=False,
        limitations=['nominal_filename_time_not_publication_proof','source_independence_not_proven',
                    'does_not_fill_2013_14_missing_outcomes','candidates_require_versioned_GT_promotion'],
        artifacts={name:digest((out/name).read_bytes()) for name in names})
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.base,a.out),indent=2))
