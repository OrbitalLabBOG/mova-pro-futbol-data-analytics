"""Audit recovered 2014/15 successor snapshots without temporal admission."""
from __future__ import annotations
import argparse
import io
import json
from pathlib import Path
import pandas as pd
from experiments.data_ground_truth.early_json_archives import normalize
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.snapshots import unpack
from experiments.data_ground_truth.training_dataset import checked,verify


def validate_inventory(records,history):
    revisions={r['sha']:r['commit']['committer']['date'] for r in history}
    if len(revisions)!=len(history) or len(records)!=len(revisions) or {r['revision'] for r in records}!=set(revisions):
        raise ValueError('incomplete or duplicate historical revisions')
    if any(r['repository']!='keithxm23/fplassistantv2' or r['path']!='data.json' for r in records):
        raise ValueError('unexpected source')
    return revisions


def inspect_snapshot(players,fixtures):
    weekly,metadata=unpack(players)
    if metadata.code.isna().any() or metadata.code.duplicated().any():raise ValueError('ambiguous player codes')
    if max(h[0] for p in players for h in p['season_history'])!='2013/14':raise ValueError('unexpected annual season')
    fallback=dict(gameweeks=sorted(int(x) for x in weekly.gw.unique()) if len(weekly) else [],
        fixtures=None,snapshot_players_without_history=int((~metadata.id.isin(weekly.id)).sum()) if len(weekly) else len(metadata),
        season_points_disagreements=None)
    if not len(weekly):return weekly,metadata,fallback|dict(normalization_status='no_history')
    try:
        labels,metadata,quality=normalize(players,fixtures,2014)
    except ValueError as error:
        return weekly,metadata,fallback|dict(normalization_status='unreconciled',normalization_error=str(error))
    return labels,metadata,quality|dict(normalization_status='reconciled')


def build(base,out):
    root=base/'early-fpl-successor-g90';raw=(root/'manifest.json').read_bytes();records=json.loads(raw)['records']
    history_raw=(base/'historical-discovery-g90/fplassistantv2-history.json').read_bytes()
    revisions=validate_inventory(records,json.loads(history_raw))
    fixture_sha='4f6c42e636040f1910a914e4c7c4d43aa4a81a00af5549daefe62b28345ed51f'
    fixtures=pd.read_csv(io.BytesIO(checked(base/'raw-history-v2/objects'/fixture_sha,fixture_sha)))
    old_raw=(base/'early-fpl-state-history-g88/manifest.json').read_bytes()
    old=json.loads(old_raw)['records'];old_shas={r['sha256'] for r in old}
    for r in old:checked(base/'early-fpl-state-history-g88/objects'/r['sha256'],r['sha256'])
    entries=[];latest=None
    for r in sorted(records,key=lambda r:(revisions[r['revision']],r['revision'])):
        data=checked(root/'objects'/r['sha256'],r['sha256'])
        if len(data)!=r['bytes']:raise ValueError('source size mismatch')
        labels,metadata,quality=inspect_snapshot(json.loads(data),fixtures)
        entries.append(dict(revision=r['revision'],source_sha256=r['sha256'],bytes=r['bytes'],
            git_committer_time=revisions[r['revision']],players=len(metadata),rows=len(labels),
            gameweeks=quality['gameweeks'],fixtures=quality['fixtures'],
            missing_history_profiles=quality['snapshot_players_without_history'],
            total_points_disagreements=quality['season_points_disagreements'],
            normalization_status=quality['normalization_status'],normalization_error=quality.get('normalization_error'),
            available_at=None,eligible_predeadline=False,eligible_training=False))
        latest=(labels,metadata,r)
    if latest is None:raise ValueError('empty history')
    labels,metadata,record=latest
    if entries[-1]['normalization_status']!='reconciled':raise ValueError('latest snapshot not reconciled')
    pointer=json.loads(Path(__file__).with_name('current-labels.json').read_text())
    package=base/'training-datasets'/pointer['dataset_id'];checked(package/'manifest.json',pointer['manifest_sha256']);gt=verify(package)
    part=next(p for p in gt['partitions'] if p['season']=='2014-15')
    existing=pd.read_csv(package/part['file'],compression='gzip')
    paired=labels.merge(existing,left_on=['id','matchId'],right_on=['element','fixture'],how='left',validate='one_to_one',indicator=True,suffixes=('_archive','_gt'))
    both=paired._merge.eq('both')
    comparison=dict(rows=len(paired),missing_in_GT=int((~both).sum()),
        minutes_conflicts=int((both&paired.mins.ne(paired.minutes)).sum()),points_conflicts=int((both&paired.gw_pts.ne(paired.total_points)).sum()),
        gameweek_conflicts=int((both&paired.gw_archive.ne(paired.gw_gt)).sum()),
        player_code_conflicts=int((both&paired.official_player_code_gt.notna()&paired.official_player_code_archive.ne(paired.official_player_code_gt)).sum()))
    out.mkdir(parents=True,exist_ok=True)
    (out/'snapshots.json').write_text(json.dumps(entries,indent=2)+'\n')
    labels['source_sha256']=record['sha256'];labels.to_csv(out/'latest-labels.csv',index=False)
    report=dict(version='early-successor-archive-v1',manifest_sha256=digest(raw),history_response_sha256=digest(history_raw),
        prior_manifest_sha256=digest(old_raw),fixture_sha256=fixture_sha,gt_dataset_id=gt['dataset_id'],
        implementation_sha256=digest(Path(__file__).read_bytes()),snapshots=len(entries),bytes=sum(r['bytes'] for r in records),
        unique_contents=len({r['sha256'] for r in records}),
        reconciled_snapshots=sum(e['normalization_status']=='reconciled' for e in entries),
        snapshots_without_history=sum(e['normalization_status']=='no_history' for e in entries),
        unreconciled_snapshots=sum(e['normalization_status']=='unreconciled' for e in entries),contents_already_in_g88=len({r['sha256'] for r in records}&old_shas),
        contents_new_vs_g88=len({r['sha256'] for r in records}-old_shas),
        earliest_git_committer_time=entries[0]['git_committer_time'],latest_git_committer_time=entries[-1]['git_committer_time'],
        latest=entries[-1],latest_GT_comparison=comparison,new_complete_seasons=0,training_admitted=False,production_changed=False,
        limitations=['git_clock_not_historic_publication_proof','collections_not_proven_atomic_snapshots',
                     '2014_15_does_not_fill_2013_14_GW34','source_overlap_not_independent_accuracy_validation'],
        artifacts={n:digest((out/n).read_bytes()) for n in ['snapshots.json','latest-labels.csv']})
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.base,a.out),indent=2))
