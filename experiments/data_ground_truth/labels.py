"""Versioned retrospective labels with official identity; never a predeadline feature feed."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3

import pandas as pd

from experiments.data_ground_truth.complement import unique_observations
from experiments.data_ground_truth.decoding import read_csv_bytes
from experiments.data_ground_truth.raw import digest
from mova_fpl.data.schema import KEY, RENAME


def build_labels(root: Path, canonical: Path) -> dict:
    manifest_bytes = (root / 'manifest.json').read_bytes()
    records = json.loads(manifest_bytes)['records']
    vaastav = {r['path']: r for r in records if r['repository'].startswith('vaastav/')}
    result = dict(version='retrospective-labels-v2', raw_manifest_sha256=digest(manifest_bytes), seasons={})
    def read(record):
        data = (root / 'objects' / record['sha256']).read_bytes()
        if digest(data) != record['sha256']:
            raise ValueError('checksum mismatch')
        return read_csv_bytes(data)
    for path, record in sorted(vaastav.items()):
        if not path.endswith('/gws/merged_gw.csv'):
            continue
        season = path.split('/')[1]
        frame, encoding = read(record)
        frame = frame.rename(columns=RENAME)
        frame['season'] = season
        frame, quality = unique_observations(frame, list(KEY))
        if quality['conflicting_rows'] or quality['null_key_rows']:
            raise ValueError('ambiguous label key')
        metadata_record = vaastav[f'data/{season}/players_raw.csv']
        metadata, _ = read(metadata_record)
        metadata, identity_quality = unique_observations(metadata[['id', 'code', 'element_type']], ['id'])
        if identity_quality['conflicting_rows'] or metadata.code.isna().any() or metadata.code.duplicated().any():
            raise ValueError('ambiguous official identity')
        metadata = metadata.rename(columns={'id': 'element', 'code': 'official_player_code', 'element_type': 'season_position_type'})
        frame = frame.merge(metadata, on='element', how='left', validate='many_to_one')
        if frame.official_player_code.isna().any():
            raise ValueError('unresolved identity')
        with sqlite3.connect(canonical.resolve().as_uri() + '?mode=ro', uri=True) as con:
            existing = pd.read_sql_query('SELECT season,gw,element,fixture,minutes,total_points FROM player_gameweek WHERE season=?', con, params=(season,))
        pairs = frame.merge(existing, on=list(KEY), how='outer', suffixes=('_raw', '_canonical'), indicator=True, validate='one_to_one')
        differences = int(((pairs['_merge'] != 'both') | (pairs.minutes_raw != pairs.minutes_canonical) | (pairs.total_points_raw != pairs.total_points_canonical)).sum())
        if differences:
            raise ValueError(f'{season}: {differences} canonical label differences')
        frame['available_at'] = None
        frame['eligible_predeadline'] = False
        frame = frame.sort_values(list(KEY))
        out = root / 'labels' / f'{season}.csv'
        out.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(out, index=False)
        result['seasons'][season] = dict(rows=len(frame), encoding=encoding, quality=quality,
            canonical_label_differences=differences, unresolved_identities=0,
            player_codes=int(frame.official_player_code.nunique()),
            source_sha256=record['sha256'], metadata_sha256=metadata_record['sha256'],
            artifact_sha256=digest(out.read_bytes()))
    (root / 'labels-manifest.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, required=True)
    ap.add_argument('--canonical', type=Path, required=True)
    args = ap.parse_args()
    print(json.dumps(build_labels(args.root, args.canonical), indent=2))


if __name__ == '__main__':
    main()
