"""Recover closed 2015/16 FPL labels from per-player API archives."""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

import pandas as pd

from experiments.data_ground_truth.historical_2014 import OPPONENT_CODES, reconcile_2014
from experiments.data_ground_truth.snapshots import unpack
from experiments.data_ground_truth.training_dataset import checked
from experiments.data_ground_truth.raw import digest


def reconcile(players: list[dict], fixtures: pd.DataFrame):
    weekly,metadata=unpack(players)
    if metadata.code.isna().any() or metadata.code.duplicated().any():
        raise ValueError('ambiguous official player identity')
    components={'mins':'minutes','goals':'goals_scored','assists':'assists','cs':'clean_sheets',
        'ga':'goals_conceded','og':'own_goals','pens_svd':'penalties_saved','pens_msd':'penalties_missed',
        'yel':'yellow_cards','red':'red_cards','saves':'saves','bonus':'bonus','bps':'bps'}
    totals=weekly.groupby('id').sum(numeric_only=True)
    disagreements={column:sum(int(totals.loc[p['id'],column]!=p[field]) for p in players)
                   for column,field in components.items()}
    if any(disagreements.values()):
        raise ValueError('season component total disagreement')
    labels,report=reconcile_2014(weekly,metadata,fixtures,season_start=2015,
        opponent_codes=OPPONENT_CODES | dict(BOU=91,NOR=45,WAT=57))
    if report['fixtures']!=380 or report['missing_fixture_ids'] or report['gameweeks']!=list(range(1,39)):
        raise ValueError('incomplete closed season')
    labels=labels.merge(metadata[['id','code','name']],on='id',validate='many_to_one').rename(columns={'code':'official_player_code'})
    report.update(component_total_disagreements=disagreements,official_identity_rows=int(labels.official_player_code.notna().sum()),
        cross_season_identity_status='official_code_per_player_archive',coverage_status='all_380_fixtures_38_gameweeks')
    return labels,report


def build(root: Path,archive_root: Path,snapshot_root: Path) -> dict:
    raw_bytes=(root/'manifest.json').read_bytes();manifest=json.loads(raw_bytes)
    players=[]
    for r in manifest['records']:
        if not r['path'].startswith('PlayersInfo/'):
            continue
        player=json.loads(checked(root/'objects'/r['sha256'],r['sha256']))
        if int(Path(r['path']).stem)!=player['id']:
            raise ValueError('player file identity mismatch')
        players.append(player)
    archive=json.loads((archive_root/'manifest.json').read_text())
    record=next(r for r in archive['records'] if r['repository'].startswith('imadeddine-belkat/') and r['path']=='pl_stats/_merged/events/2015-16_events_stats.csv')
    fixtures=pd.read_csv(io.BytesIO(checked(archive_root/'objects'/record['sha256'],record['sha256'])))
    labels,report=reconcile(players,fixtures)
    partial_report=json.loads((snapshot_root/'report.json').read_text())['seasons']['2015-16']
    partial_data=checked(snapshot_root/'labels/2015-16/labels.csv',partial_report['labels_sha256'])
    partial=pd.read_csv(io.BytesIO(partial_data))
    paired=partial.merge(labels,on=['id','matchId'],how='left',suffixes=('_partial','_full'),indicator=True,validate='one_to_one')
    differences={c:int(paired[c+'_partial'].ne(paired[c+'_full']).sum()) for c in ['mins','gw_pts','gw','official_player_code']}
    if paired['_merge'].ne('both').any() or any(differences.values()):
        raise ValueError('partial snapshot reconciliation disagreement')
    target=root/'labels.csv';labels.to_csv(target,index=False)
    report.update(version='fpl-2015-labels-v1',raw_manifest_sha256=digest(raw_bytes),
        fixture_source_sha256=record['sha256'],partial_source_sha256=digest(partial_data),
        verified_partial_rows=len(paired),partial_disagreements=differences,
        additional_rows_vs_partial=len(labels)-len(partial),
        additional_players_vs_partial=int(labels.id.nunique()-partial.id.nunique()),
        additional_fixtures_vs_partial=int(labels.matchId.nunique()-partial.matchId.nunique()),
        labels_sha256=digest(target.read_bytes()))
    (root/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root',type=Path,required=True);ap.add_argument('--archive-root',type=Path,required=True)
    ap.add_argument('--snapshot-root',type=Path,required=True)
    args=ap.parse_args();print(json.dumps(build(args.root,args.archive_root,args.snapshot_root),indent=2))


if __name__=='__main__':
    main()
