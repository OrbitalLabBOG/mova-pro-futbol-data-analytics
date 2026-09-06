"""Audit historical database overlap and extract retrospective FPL season totals."""
from __future__ import annotations

import argparse
import io
import json
import re
from pathlib import Path

import pandas as pd

from experiments.data_ground_truth.differential_audit import read_tables
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked


def compare_versions(versions: dict[str,pd.DataFrame]):
    keys=['season','player_player_id','fixture_id'];frames=[];source_counts={}
    for source,frame in versions.items():
        frame=frame[frame.season.isin([12,13,14])].copy()
        if frame.empty:continue
        if frame.duplicated(keys).any():raise ValueError('duplicate archived appearance')
        source_counts[source]={str(int(s)):dict(rows=len(g),observed_rows=int((g.minutes.notna() & g.total.notna()).sum())) for s,g in frame.groupby('season')}
        frames.append(frame[keys+['minutes','total']].assign(source=source))
    if not frames:raise ValueError('no historical database versions')
    combined=pd.concat(frames,ignore_index=True);seasons={}
    for season,frame in combined.groupby('season'):
        observed=frame[frame.minutes.notna() & frame.total.notna()]
        counts=frame.groupby(keys)[['minutes','total']].nunique(dropna=True)
        conflicts=counts.gt(1).any(axis=1)
        best=max(info.get(str(int(season)),{}).get('observed_rows',0) for info in source_counts.values())
        seasons[str(int(season))]=dict(season=f'{1999+int(season)}-{str(2000+int(season))[-2:]}',
            archived_versions=int(frame.source.nunique()),union_keys=len(counts),
            union_observed_keys=len(observed.drop_duplicates(keys)),
            best_single_version_observed_rows=best,
            additional_observed_keys_over_best=len(observed.drop_duplicates(keys))-best,
            conflicting_keys=int(conflicts.sum()),
            conflicting_key_examples=[list(k) for k in counts.index[conflicts].tolist()[:20]])
    return dict(sources=source_counts,seasons=seasons,
        null_policy='preserved_not_filled_or_composed_between_versions')


def extract_histories(players: list[dict]):
    rows=[]
    for player in players:
        for history in player['season_history']:
            if len(history)!=17:raise ValueError('unknown season history schema')
            season,minutes,points=history[0],history[1],history[-1]
            if not isinstance(season,str) or not re.fullmatch(r'[0-9]{4}/[0-9]{2}',season) or (int(season[:4])+1)%100!=int(season[-2:]):
                raise ValueError('invalid historical season')
            if not isinstance(minutes,int) or isinstance(minutes,bool) or minutes<0:
                raise ValueError('invalid historical minutes')
            if not isinstance(points,int) or isinstance(points,bool):raise ValueError('invalid historical points')
            rows.append(dict(season=season,official_player_code=int(player['code']),
                first_name=player['first_name'],second_name=player['second_name'],
                minutes=minutes,points=points,source_sha256=player['source_sha256'],
                available_at=None,eligible_predeadline=False,eligible_training=False,
                observation_unit='player_season',population='players_present_in_2015_16_archive'))
    frame=pd.DataFrame(rows)
    if frame.duplicated(['season','official_player_code']).any():raise ValueError('duplicate season identity')
    return frame.sort_values(['season','official_player_code']).reset_index(drop=True)


def reconcile_totals(histories: pd.DataFrame,labels: pd.DataFrame):
    reference=labels.dropna(subset=['official_player_code']).groupby('official_player_code').agg(minutes=('mins','sum'),points=('gw_pts','sum'))
    joined=histories[histories.season.eq('2014/15')].merge(reference,left_on='official_player_code',right_index=True,
        how='left',suffixes=('','_reference'),indicator=True,validate='one_to_one')
    matched=joined['_merge'].eq('both')
    diff=matched & (joined.minutes.ne(joined.minutes_reference)|joined.points.ne(joined.points_reference))
    if diff.any():raise ValueError('historical season total disagreement')
    unknown=joined[~matched]
    return dict(season='2014/15',matched_players=int(matched.sum()),disagreements=int(diff.sum()),
        unmatched_players=len(unknown),unmatched_positive_minutes=int(unknown.minutes.gt(0).sum()),
        unmatched_status='not_proof_of_historical_registration_or_fixture_eligibility')


def build(database_root: Path,later_root: Path,identity_root: Path,out: Path):
    database_manifest=json.loads((database_root/'manifest.json').read_text());versions={};database_hashes={}
    for rec in database_manifest['records']:
        if rec['path'].endswith('.db3') and not rec['path'].endswith('DiffGen_11_37.db3'):
            path=database_root/'objects'/rec['sha256'];checked(path,rec['sha256'])
            versions[rec['path']]=read_tables(path)['player_match'];database_hashes[rec['path']]=rec['sha256']
    later_bytes=(later_root/'manifest.json').read_bytes();players=[]
    for rec in json.loads(later_bytes)['records']:
        if rec['path'].startswith('PlayersInfo/'):
            p=json.loads(checked(later_root/'objects'/rec['sha256'],rec['sha256']));p['source_sha256']=rec['sha256'];players.append(p)
    histories=extract_histories(players)
    identity=json.loads((identity_root/'identity/report.json').read_text())
    labels=pd.read_csv(io.BytesIO(checked(identity_root/'identity/labels.csv',identity['labels_sha256'])))
    comparison=reconcile_totals(histories,labels)
    out.mkdir(parents=True,exist_ok=True);histories.to_csv(out/'season_totals.csv',index=False)
    report=dict(version='historical-season-evidence-v1',database_overlap=compare_versions(versions),
        season_total_rows=len(histories),season_counts={s:len(g) for s,g in histories.groupby('season')},
        complete_population_seasons=0,comparison=comparison,
        source_database_sha256=database_hashes,later_manifest_sha256=digest(later_bytes),
        reference_labels_sha256=identity['labels_sha256'],season_totals_sha256=digest((out/'season_totals.csv').read_bytes()),
        selection_bias='survivors_present_in_2015_16_not_complete_historical_population',
        new_complete_fpl_seasons=0)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for arg in ['database-root','later-root','identity-root','out']:ap.add_argument('--'+arg,type=Path,required=True)
    args=ap.parse_args();print(json.dumps(build(args.database_root,args.later_root,args.identity_root,args.out),indent=2))


if __name__=='__main__':main()
