"""Read-only audit of archived Differential databases; no training promotion."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3

import pandas as pd

from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked

TABLES=('player_match','player_season','fixture')


def read_tables(path: Path):
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro&immutable=1',uri=True) as connection:
        connection.execute('PRAGMA trusted_schema=OFF')
        connection.execute('PRAGMA query_only=ON')
        available={r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not set(TABLES)<=available:
            raise ValueError('missing physical archive tables')
        if connection.execute('PRAGMA quick_check').fetchall()!=[('ok',)]:
            raise ValueError('archive integrity failure')
        return {table:pd.read_sql_query(f'SELECT * FROM {table}',connection) for table in TABLES}


def quality(tables: dict) -> dict:
    matches=tables['player_match'];metadata=tables['player_season'];fixtures=tables['fixture']
    player_key='player_player_id' if 'player_player_id' in matches else 'player_fpl_id'
    metadata_key='player_id' if player_key=='player_player_id' else 'fpl_id'
    result={}
    for season,frame in matches.groupby('season'):
        observed=frame.minutes.notna() & frame.total.notna()
        sums=frame.groupby(player_key).agg(points=('total',lambda s:s.sum(min_count=1)),minutes=('minutes',lambda s:s.sum(min_count=1))).reset_index().rename(columns={player_key:'observed_player_id'})
        comparison=metadata[metadata.season.eq(season)][[metadata_key,'points','minutes']].merge(sums,
            left_on=metadata_key,right_on='observed_player_id',how='outer',suffixes=('_snapshot','_rows'),indicator=True,validate='one_to_one')
        both=comparison['_merge'].eq('both')
        comparable=both & comparison.points_rows.notna() & comparison.minutes_rows.notna()
        differences=comparable & (comparison.points_snapshot.ne(comparison.points_rows)|comparison.minutes_snapshot.ne(comparison.minutes_rows))
        fixture=fixtures[fixtures.season.eq(season)]
        joined=frame[['fixture_id']].merge(fixture[['_id']],left_on='fixture_id',right_on='_id',how='left',validate='many_to_one',indicator=True)
        result[str(int(season))]=dict(
            season=f'{1999+int(season)}-{str(2000+int(season))[-2:]}',rows=len(frame),
            referenced_gameweeks=sorted(int(x) for x in frame.gameweek.dropna().unique()),
            gameweeks_with_both_labels=sorted(int(x) for x in frame.loc[observed,'gameweek'].dropna().unique()),
            player_ids=int(frame[player_key].nunique()),source_player_key=player_key,referenced_fixtures=int(frame.fixture_id.nunique()),
            fixtures_with_both_labels=int(frame.loc[observed,'fixture_id'].nunique()),
            raw_fixture_rows=len(fixture),unresolved_fixture_rows=int(joined['_merge'].ne('both').sum()),
            rows_with_both_labels=int(observed.sum()),missing_minutes=int(frame.minutes.isna().sum()),
            missing_points=int(frame.total.isna().sum()),explicit_zero_minutes=int(frame.minutes.eq(0).sum()),
            invalid_minutes=int((frame.minutes.notna() & ~frame.minutes.between(0,90)).sum()),
            duplicate_keys=int(frame.duplicated([player_key,'fixture_id']).sum()),
            comparable_player_totals=int(comparable.sum()),player_total_disagreements=int(differences.sum()),
            players_without_match_rows=int(comparison['_merge'].eq('left_only').sum()),
            positive_minutes_players_without_match_rows=int((comparison['_merge'].eq('left_only') & comparison.minutes_snapshot.gt(0)).sum()),
            missing_appearance_player_ids=[int(x) for x in comparison.loc[comparison['_merge'].eq('left_only') & comparison.minutes_snapshot.gt(0),metadata_key]],
            players_without_season_metadata=int(comparison['_merge'].eq('right_only').sum()),
            status='unreconciled_archive_not_full_season_ground_truth')
    return result


def build(root: Path) -> dict:
    manifest=json.loads((root/'manifest.json').read_text());databases={}
    for record in manifest['records']:
        if not record['path'].endswith('.db3'):
            continue
        path=root/'objects'/record['sha256'];checked(path,record['sha256'])
        tables=read_tables(path)
        databases[record['path']]=dict(sha256=record['sha256'],seasons=quality(tables))
        if record['path']=='Differential/Database/diffgen16.db3':
            # Explicit allowlist: do not export forecasts, calculated scores or manager tables.
            columns=['season','player_player_id','fixture_id','pl_team_id','opp_team_id','gameweek',
                'minutes','total','goals','assists','bonus','conceded','pen_sav','pen_miss','yellow','red','saves','own_goals','bps']
            frame=tables['player_match'][columns].copy()
            frame['source_sha256']=record['sha256'];frame['available_at']=None
            frame['eligible_predeadline']=False;frame['eligible_training']=False
            dest=root/'staging';dest.mkdir(parents=True,exist_ok=True)
            frame.to_csv(dest/'unreconciled_player_match.csv',index=False)
            databases[record['path']]['staging_sha256']=digest((dest/'unreconciled_player_match.csv').read_bytes())
    report=dict(version='differential-archive-audit-v1',databases=databases,
        null_policy='preserve_unknown_never_assume_zero',
        source_selection_bias='history_and_live_cache_not_complete_registered_player_universe',
        promotion_status='excluded_from_training_package',new_complete_seasons=0)
    (root/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--root',type=Path,required=True)
    args=ap.parse_args();print(json.dumps(build(args.root),indent=2))


if __name__=='__main__':
    main()
