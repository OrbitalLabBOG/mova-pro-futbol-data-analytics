"""Validate partial archived labels and derive venue without overwriting raw NULLs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from experiments.data_ground_truth.differential_audit import read_tables
from experiments.data_ground_truth.historical_null_coverage import DATABASE_SHA
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked


def audit(tables: dict) -> tuple[pd.DataFrame, dict]:
    keys = ['season', 'player_player_id', 'fixture_id']
    columns = keys + ['gameweek', 'pl_team_id', 'opp_team_id', 'is_home', 'minutes', 'total']
    frame = tables['player_match'].loc[lambda x: x.season.isin((12, 13, 14)), columns].copy()
    fixtures = tables['fixture'][['season', '_id', 'gameweek', 'team_home_id', 'team_away_id']].rename(
        columns={'_id': 'fixture_id', 'gameweek': 'fixture_gameweek'})
    metadata = tables['player_season'][['season', 'player_id', 'fpl_id']].rename(
        columns={'player_id': 'player_player_id', 'fpl_id': 'season_fpl_id'})
    # Ambiguous dimension keys invalidate the source; never silently fan out observations.
    frame = frame.merge(fixtures, on=['season', 'fixture_id'], how='left', validate='many_to_one', indicator='_fixture')
    frame = frame.merge(metadata, on=['season', 'player_player_id'], how='left', validate='many_to_one', indicator='_player')
    home = frame.pl_team_id.eq(frame.team_home_id) & frame.opp_team_id.eq(frame.team_away_id)
    away = frame.pl_team_id.eq(frame.team_away_id) & frame.opp_team_id.eq(frame.team_home_id)
    pair = (home ^ away) & frame._fixture.eq('both')
    frame['derived_is_home'] = pd.Series(pd.NA, index=frame.index, dtype='Int64')
    frame.loc[pair, 'derived_is_home'] = home.loc[pair].astype(int)
    errors = {
        'missing_native_key': frame[keys].isna().any(axis=1),
        'duplicate_native_key': frame.duplicated(keys, keep=False),
        'missing_fixture': frame._fixture.ne('both'),
        'missing_player_metadata': frame._player.ne('both') | frame.season_fpl_id.isna(),
        'invalid_gameweek': ~frame.gameweek.between(1, 38) | frame.gameweek.mod(1).ne(0),
        'gameweek_conflict': frame.gameweek.ne(frame.fixture_gameweek),
        'invalid_club_pair': ~pair,
        'venue_conflict': frame.is_home.notna() & (frame.is_home.ne(frame.derived_is_home).fillna(True)),
        'missing_minutes': frame.minutes.isna(),
        'invalid_minutes': frame.minutes.notna() & (~frame.minutes.between(0, 90) | frame.minutes.mod(1).ne(0)),
        'missing_points': frame.total.isna(),
        'invalid_points': frame.total.notna() & frame.total.mod(1).ne(0),
    }
    flags = pd.DataFrame(errors).fillna(True).astype(bool)
    frame['quality_issues'] = flags.apply(lambda row: '|'.join(row.index[row]), axis=1)
    frame['structurally_valid_observed_label'] = ~flags.any(axis=1)
    frame['venue_derivation'] = pair.map({True: 'same_season_fixture_club_pair', False: 'unresolved'})
    frame['source_sha256'] = DATABASE_SHA
    frame['identity_namespace'] = 'differential_native_player_id_season_scoped'
    frame['available_at'] = None
    frame['eligible_predeadline'] = False
    frame['eligible_training'] = False
    seasons = {}
    for season, group in frame.groupby('season'):
        valid = group.structurally_valid_observed_label
        seasons[str(int(season))] = dict(
            archived_rows=len(group), observed_label_rows=int((group.minutes.notna() & group.total.notna()).sum()),
            structurally_valid_observed_labels=int(valid.sum()),
            fixtures_with_valid_labels=int(group.loc[valid, 'fixture_id'].nunique()),
            venue_derived_from_clubs=int(group.derived_is_home.notna().sum()),
            raw_venue_nulls_resolved=int((group.is_home.isna() & group.derived_is_home.notna()).sum()),
            issues={key: int(value.loc[group.index].sum()) for key, value in flags.items()},
        )
    frame = frame.drop(columns=['_fixture', '_player']).sort_values(keys, kind='stable').reset_index(drop=True)
    return frame, seasons


def build(database: Path, out: Path) -> dict:
    checked(database, DATABASE_SHA)
    frame, seasons = audit(read_tables(database))
    out.mkdir(parents=True, exist_ok=True)
    path = out / 'partial_observations.csv'
    frame.to_csv(path, index=False)
    report = dict(version='partial-history-integrity-v1', database_sha256=DATABASE_SHA,
                  implementation_sha256=digest(Path(__file__).read_bytes()), seasons=seasons,
                  artifacts={path.name: digest(path.read_bytes())},
                  new_label_rows=0, new_complete_seasons=0, training_admitted=False,
                  limitations=['structural_checks_not_independent_label_accuracy',
                               'registered_player_population_unknown_selection_bias',
                               'season_fpl_id_not_cross_season_official_player_code',
                               'raw_nulls_preserved_venue_is_separate_derivation',
                               'no_predeadline_availability_proof'])
    (out / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.database, args.out), indent=2))
