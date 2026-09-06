"""Recover partial historical snapshots; never claim full season or deadline coverage."""
from __future__ import annotations

import argparse
import ast
import io
import json
from pathlib import Path

import pandas as pd

from experiments.data_ground_truth.historical_2014 import OPPONENT_CODES, reconcile_2014
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked

COLUMNS=['date','gw','opp','mins','goals','assists','cs','ga','og','pens_svd','pens_msd',
         'yel','red','saves','bonus','ea_ppi','bps','net_transfers','gw_val','gw_pts']


def unpack(players: list[dict]) -> tuple[pd.DataFrame,pd.DataFrame]:
    rows=[];metadata=[]
    for player in players:
        history=player['fixture_history']
        if isinstance(history,str):
            history=ast.literal_eval(history)
        metadata.append(dict(id=int(player['id']),pts=int(player['total_points']),
            code=player.get('code'),name=player['web_name']))
        for values in history['all']:
            if len(values)!=len(COLUMNS):
                raise ValueError('unknown snapshot history schema')
            rows.append(dict(zip(COLUMNS,values),id=int(player['id'])))
    metadata=pd.DataFrame(metadata)
    if metadata.id.duplicated().any():
        raise ValueError('duplicate snapshot player ID')
    return pd.DataFrame(rows),metadata


def enrich_identity(labels: pd.DataFrame, snapshot: pd.DataFrame):
    """Same season IDs, matching observed labels and unique explicit official codes."""
    pairs=snapshot.merge(labels,on=['id','matchId'],suffixes=('_snapshot','_full'),
        how='left',validate='one_to_one',indicator=True)
    if pairs['_merge'].ne('both').any() or any(pairs[c+'_snapshot'].ne(pairs[c+'_full']).any() for c in ['mins','gw_pts','gw']):
        raise ValueError('snapshot ground truth disagreement')
    identities=snapshot[['id','official_player_code']].drop_duplicates()
    if identities.id.duplicated().any() or identities.official_player_code.duplicated().any() or identities.official_player_code.isna().any():
        raise ValueError('ambiguous snapshot identity')
    joined=labels.merge(identities,on='id',how='left',validate='many_to_one',suffixes=('','_snapshot'))
    both=joined.official_player_code.notna() & joined.official_player_code_snapshot.notna()
    if joined.loc[both,'official_player_code'].ne(joined.loc[both,'official_player_code_snapshot']).any():
        raise ValueError('conflicting snapshot identity')
    new=joined.official_player_code.isna() & joined.official_player_code_snapshot.notna()
    joined.loc[new,'official_player_code']=joined.loc[new,'official_player_code_snapshot']
    joined.loc[new,'identity_status']='official_snapshot_id_and_observation_match'
    resolved=joined[['id','official_player_code']].dropna().drop_duplicates()
    if resolved.official_player_code.duplicated().any():
        raise ValueError('cross-source identity collision')
    return joined.drop(columns='official_player_code_snapshot'),dict(
        verified_overlap_rows=len(pairs),added_identity_rows=int(new.sum()),
        added_players=int(joined.loc[new,'id'].nunique()),
        resolved_players=int(resolved.id.nunique()),unresolved_players=int(joined.loc[joined.official_player_code.isna(),'id'].nunique()),
        resolved_rows=int(joined.official_player_code.notna().sum()),
        resolved_played_rows=int((joined.official_player_code.notna() & joined.mins.gt(0)).sum()),
        played_rows=int(joined.mins.gt(0).sum()))


def build(root: Path,archive_root: Path,old_root: Path | None = None) -> dict:
    manifest=json.loads((root/'manifest.json').read_text())
    archive=json.loads((archive_root/'manifest.json').read_text())
    report=dict(version='historical-partial-snapshots-v1',seasons={})
    for season,start,repository,path in [
        ('2014-15',2014,'prathmesh/','Data/dec15_players.csv'),
        ('2015-16',2015,'clwatkins/','Data/FPL_API_Dump.json')]:
        record=next(r for r in manifest['records'] if r['repository'].startswith(repository) and r['path']==path)
        data=checked(root/'objects'/record['sha256'],record['sha256'])
        players=pd.read_csv(io.BytesIO(data)).to_dict('records') if start==2014 else list(json.loads(data).values())
        weekly,metadata=unpack(players)
        pending=weekly.opp.str.fullmatch(r'[A-Z]{3}\([HA]\) ')
        quarantine=weekly.loc[pending].copy()
        outcome_columns=COLUMNS[3:17]+['gw_pts']
        if not quarantine[outcome_columns].apply(pd.to_numeric,errors='raise').eq(0).all().all():
            raise ValueError('unscored fixture with nonzero outcome')
        quarantine['exclusion_reason']='fixture_without_result_in_snapshot'
        weekly=weekly.loc[~pending].copy()
        fixture_record=next(r for r in archive['records'] if r['repository'].startswith('imadeddine-belkat/') and r['path']==f'pl_stats/_merged/events/{season}_events_stats.csv')
        fixtures=pd.read_csv(io.BytesIO(checked(archive_root/'objects'/fixture_record['sha256'],fixture_record['sha256'])))
        codes=OPPONENT_CODES | dict(BOU=91,NOR=45,WAT=57)
        labels,quality=reconcile_2014(weekly,metadata,fixtures,season_start=start,opponent_codes=codes)
        labels=labels.merge(metadata[['id','code','name']],on='id',validate='many_to_one').rename(columns={'code':'official_player_code'})
        labels['coverage_status']='partial_snapshot_not_full_season'
        dest=root/'labels'/season;dest.mkdir(parents=True,exist_ok=True)
        labels.to_csv(dest/'labels.csv',index=False)
        metadata.to_csv(dest/'identities.csv',index=False)
        quarantine.to_csv(dest/'quarantine.csv',index=False)
        quality.update(quarantined_unscored_rows=len(quarantine),quarantine_sha256=digest((dest/'quarantine.csv').read_bytes()),source_sha256=record['sha256'],fixture_sha256=fixture_record['sha256'],
            labels_sha256=digest((dest/'labels.csv').read_bytes()),identity_sha256=digest((dest/'identities.csv').read_bytes()),
            coverage_status='partial_snapshot_not_full_season',
            player_universe_status='snapshot_roster_not_complete_season',
            source_key='player_id' if start==2014 else 'web_name_potential_upstream_collision',
            official_identity_rows=int(labels.official_player_code.notna().sum()))
        quality['snapshot_points_disagreements']=quality.pop('season_points_disagreements')
        quality['cross_season_identity_status']='snapshot_codes_only_where_present'
        report['seasons'][season]=quality
    if old_root is not None:
        old_report=json.loads((old_root/'identity/report.json').read_text())
        old_data=checked(old_root/'identity/labels.csv',old_report['labels_sha256'])
        snapshot=checked(root/'labels/2014-15/labels.csv',report['seasons']['2014-15']['labels_sha256'])
        enriched,identity_report=enrich_identity(pd.read_csv(io.BytesIO(old_data)),pd.read_csv(io.BytesIO(snapshot)))
        dest=root/'identity';dest.mkdir(parents=True,exist_ok=True)
        enriched.to_csv(dest/'labels.csv',index=False)
        identity_report.update(labels_sha256=digest((dest/'labels.csv').read_bytes()),
            prior_labels_sha256=old_report['labels_sha256'],snapshot_labels_sha256=digest(snapshot))
        (dest/'report.json').write_text(json.dumps(identity_report,indent=2)+'\n')
        report['identity_2014']=identity_report
    (root/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root',type=Path,required=True);ap.add_argument('--archive-root',type=Path,required=True)
    ap.add_argument('--old-root',type=Path)
    args=ap.parse_args();print(json.dumps(build(args.root,args.archive_root,args.old_root),indent=2))


if __name__=='__main__':
    main()
