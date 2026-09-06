"""Reconcile supplementary observations; export quarantined research tables only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3

import pandas as pd

from experiments.data_ground_truth.raw import digest


def unique_observations(frame: pd.DataFrame, keys: list[str]) -> tuple[pd.DataFrame, dict]:
    """Do not choose an arbitrary revision when two rows disagree."""
    clean = frame.drop_duplicates()
    null = clean[keys].isna().any(axis=1)
    conflict = clean.duplicated(keys, keep=False)
    return clean.loc[~(null | conflict)].copy(), dict(
        input_rows=len(frame), exact_duplicates=len(frame) - len(clean),
        conflicting_rows=int(conflict.sum()), null_key_rows=int(null.sum()),
        retained_rows=int((~(null | conflict)).sum()))


def reconcile(db: Path, root: Path) -> dict:
    manifest = json.loads((root / 'manifest.json').read_text())
    results = {}
    for long_season in ('2024-2025', '2025-2026', '2026-2027'):
        frames = {}
        for r in manifest['records']:
            if not r['repository'].startswith('olbauday/') or not r['path'].startswith(f'data/{long_season}/') or not r['path'].endswith('.csv'):
                continue
            if '/GW' not in r['path'] and not r['path'].endswith('/players/players.csv'):
                continue
            blob = root / 'objects' / r['sha256']
            if digest(blob.read_bytes()) != r['sha256']:
                raise ValueError('raw checksum mismatch')
            df = pd.read_csv(blob, low_memory=False)
            kind = Path(r['path']).stem
            frames.setdefault(kind, []).append(df)
        if not {'matches', 'playermatchstats'} <= frames.keys():
            continue
        matches, match_quality = unique_observations(pd.concat(frames['matches'], ignore_index=True), ['match_id'])
        stats, stats_quality = unique_observations(pd.concat(frames['playermatchstats'], ignore_index=True), ['match_id', 'player_id'])
        # Preserve upstream fields, with all publication times explicitly unknown.
        metadata_cols = [c for c in ['match_id', 'kickoff_time', 'tournament', 'finished'] if c in matches]
        joined = stats.merge(matches[metadata_cols], on='match_id', how='left', validate='many_to_one', indicator=True)
        joined['source_available_at'] = None
        joined['eligible_predeadline'] = False
        joined['season'] = long_season
        out = root / 'staging' / long_season
        out.mkdir(parents=True, exist_ok=True)
        joined.to_csv(out / 'player_match_observations.csv', index=False)
        tournaments = matches.groupby('tournament', dropna=False).size().to_dict() if 'tournament' in matches else {}
        result = dict(match_quality=match_quality, player_match_quality=stats_quality,
                      tournaments={str(k): int(v) for k, v in tournaments.items()},
                      finished_matches=int(matches.finished.eq(True).sum()) if 'finished' in matches else None,
                      player_rows_without_match=int((joined['_merge'] != 'both').sum()),
                      player_rows_without_valid_kickoff=int(pd.to_datetime(joined.kickoff_time, errors='coerce', utc=True, format='mixed').isna().sum()) if 'kickoff_time' in joined else len(joined),
                      observed_minutes_rows=int(joined.minutes_played.notna().sum()),
                      invalid_minutes_rows=int(((joined.minutes_played < 0) | (joined.minutes_played > 130)).sum()),
                      staging_sha256=digest((out / 'player_match_observations.csv').read_bytes()))
        short_season = long_season[:5] + long_season[-2:]
        with sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True) as con:
            canonical = pd.read_sql_query('SELECT element,gw,total_points,minutes FROM player_gameweek WHERE season=?', con, params=(short_season,))
        result['player_rows_with_canonical_element'] = int(joined.player_id.isin(canonical.element).sum())
        if 'players' in frames:
            source_ids = pd.concat(frames['players'], ignore_index=True)[['player_id', 'player_code']].drop_duplicates()
            resolved, identity_quality = unique_observations(source_ids, ['player_id'])
            crosswalk_path = root / 'staging' / short_season / 'player_identity.csv'
            if crosswalk_path.exists():
                official = pd.read_csv(crosswalk_path)
                paired_ids = resolved.merge(official, left_on='player_id', right_on='element', validate='one_to_one')
                result['identity_reconciliation'] = dict(quality=identity_quality, paired_players=len(paired_ids),
                    code_disagreements=int((paired_ids.player_code != paired_ids.official_player_code).sum()),
                    source_players_without_canonical_metadata=int((~resolved.player_id.isin(official.element)).sum()))
        if 'player_gameweek_stats' in frames and not canonical.empty:
            weekly, quality = unique_observations(pd.concat(frames['player_gameweek_stats'], ignore_index=True), ['id', 'gw'])
            actual = canonical.groupby(['element', 'gw'])[['total_points', 'minutes']].sum(min_count=1).reset_index()
            paired = actual.merge(weekly[['id', 'gw', 'total_points', 'minutes']], left_on=['element', 'gw'], right_on=['id', 'gw'], suffixes=('_canonical', '_core'), validate='one_to_one')
            result['weekly_reconciliation'] = dict(quality=quality, canonical_player_weeks=len(actual), paired_rows=len(paired),
                points_disagreements=int((paired.total_points_canonical != paired.total_points_core).sum()),
                minutes_disagreements=int((paired.minutes_canonical != paired.minutes_core).sum()),
                negative_minutes_rows=int((weekly.minutes < 0).sum()))
        results[long_season] = result
    (root / 'complement.json').write_text(json.dumps(results, indent=2) + '\n')
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--db', type=Path, required=True)
    ap.add_argument('--root', type=Path, required=True)
    args = ap.parse_args()
    print(json.dumps(reconcile(args.db, args.root), indent=2))


if __name__ == '__main__':
    main()
