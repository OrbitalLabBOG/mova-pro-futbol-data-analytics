"""Measure historical labels and raw-source coverage, without modifying canonical data."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3

import pandas as pd

from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.decoding import read_csv_bytes
from mova_fpl.data.schema import KEY


def frame_quality(frame: pd.DataFrame) -> dict:
    played = frame.loc[frame['minutes'].fillna(0) > 0]
    identities = frame[['element', 'player_key']].drop_duplicates().dropna()
    collisions = identities.groupby('player_key').element.nunique()
    return dict(
        rows=len(frame), players=int(frame.element.nunique()), fixtures=int(frame.fixture.nunique()),
        gameweeks=sorted(int(x) for x in frame.gw.dropna().unique()),
        duplicate_keys=int(frame.duplicated(list(KEY)).sum()),
        null_keys=int(frame[list(KEY)].isna().any(axis=1).sum()),
        invalid_minutes=int(((frame.minutes < 0) | (frame.minutes > 90)).sum()),
        invalid_kickoff=int(pd.to_datetime(frame.kickoff_time, errors='coerce', utc=True, format='mixed').isna().sum()),
        ambiguous_name_keys={k: int(v) for k, v in collisions.items() if v > 1},
        columns={c: dict(non_null=int(frame[c].notna().sum()), rows=len(frame),
                         played_non_null=int(played[c].notna().sum()), played_rows=len(played))
                 for c in frame.columns},
    )


def audit(db: Path, root: Path) -> dict:
    manifest = json.loads((root / 'manifest.json').read_text())
    tables = {}
    inventory = []
    for record in manifest['records']:
        blob = root / 'objects' / record['sha256']
        if digest(blob.read_bytes()) != record['sha256']:
            raise ValueError('raw checksum mismatch')
        if not record['path'].endswith('.csv'):
            continue
        try:
            df, encoding = read_csv_bytes(blob.read_bytes())
        except (ValueError, UnicodeDecodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
            inventory.append(dict(repository=record['repository'], path=record['path'],
                                  sha256=record['sha256'], parse_error=type(exc).__name__))
            continue
        if record['repository'].startswith('vaastav/') and record['path'].endswith(('/players_raw.csv', '/fixtures.csv')):
            tables[(record['repository'], record['path'])] = df
        inventory.append(dict(repository=record['repository'], path=record['path'], rows=len(df), encoding=encoding,
                              columns=list(df.columns), nulls={c: int(df[c].isna().sum()) for c in df.columns},
                              sha256=record['sha256']))
    seasons = {}
    with sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True) as con:
        for (season,) in con.execute('SELECT DISTINCT season FROM player_gameweek ORDER BY season'):
            df = pd.read_sql_query('SELECT * FROM player_gameweek WHERE season=?', con, params=(season,))
            result = frame_quality(df)
            prefix = 'data/' + season + '/'
            meta = tables.get(('vaastav/Fantasy-Premier-League', prefix + 'players_raw.csv'))
            if meta is not None:
                # Per-season official element ID; never a fuzzy name join or final club backfill.
                unique = meta.drop_duplicates('id', keep=False)
                position = df.element.map(unique.set_index('id')['element_type'])
                code = df.element.map(unique.set_index('id')['code']) if 'code' in unique else pd.Series(index=df.index, dtype=float)
                staging = root / 'staging' / season
                staging.mkdir(parents=True, exist_ok=True)
                crosswalk = unique[['id', 'code', 'element_type']].rename(columns={'id': 'element', 'code': 'official_player_code', 'element_type': 'season_position_type'})
                crosswalk['season'] = season
                crosswalk['source_available_at'] = None
                crosswalk['eligible_predeadline'] = False
                crosswalk.to_csv(staging / 'player_identity.csv', index=False)
                result['metadata_join'] = dict(
                    identity_artifact_sha256=digest((staging / 'player_identity.csv').read_bytes()),
                    duplicate_official_codes=int(unique.code.duplicated(keep=False).sum()),
                    matched_rows=int(df.element.isin(unique.id).sum()),
                    unmatched_elements=sorted(int(x) for x in set(df.element) - set(unique.id)),
                    duplicate_metadata_ids=int(meta.id.duplicated(keep=False).sum()),
                    missing_position_recoverable=int((df.position.isna() & position.notna()).sum()),
                    stable_code_rows=int(code.notna().sum()),
                    status='research_only_final_season_metadata_not_predeadline',
                )
            fixtures = tables.get(('vaastav/Fantasy-Premier-League', prefix + 'fixtures.csv'))
            if fixtures is not None:
                expected = set(fixtures.loc[fixtures.finished == True, 'id'])
                result['fixture_join'] = dict(finished_source_fixtures=len(expected),
                    missing_finished_ids=sorted(int(x) for x in expected - set(df.fixture)),
                    unmatched_canonical_ids=sorted(int(x) for x in set(df.fixture) - set(fixtures.id)))
            seasons[season] = result
    with db.open('rb') as stream:
        db_sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    return dict(schema_version=1, canonical_sha256=db_sha, pins=manifest['pins'],
                raw_files=len(manifest['records']), raw_bytes=sum(r['bytes'] for r in manifest['records']),
                acquisition_errors=manifest['errors'], seasons=seasons, raw_csv_inventory=inventory,
                parse_errors=[x for x in inventory if 'parse_error' in x],
                predeadline_eligible_files=sum(r['eligible_predeadline'] for r in manifest['records']))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--db', type=Path, required=True)
    ap.add_argument('--root', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    report = audit(args.db, args.root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('seasons', 'raw_csv_inventory')}))
    for season, data in report['seasons'].items():
        print(season, json.dumps({k: v for k, v in data.items() if k != 'columns'}))


if __name__ == '__main__':
    main()
