"""Resolve archive namespaces by season's unique home/away club pair."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from experiments.data_ground_truth.raw import digest


def fixture_crosswalk(players: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    sides = players[['matchId','venue','team_id']].drop_duplicates()
    if not sides.venue.isin(['Home','Away']).all():
        raise ValueError('unknown venue')
    home = sides.loc[sides.venue.eq('Home'), ['matchId','team_id']].rename(columns={'team_id':'home_team_id'})
    away = sides.loc[sides.venue.eq('Away'), ['matchId','team_id']].rename(columns={'team_id':'away_team_id'})
    if home.matchId.duplicated().any() or away.matchId.duplicated().any():
        raise ValueError('conflicting match participants')
    pairs = home.merge(away, on='matchId', how='outer', validate='one_to_one')
    if pairs.isna().any().any():
        raise ValueError('missing match participant')
    pair = ['home_team_id','away_team_id']
    if events.matchId.duplicated().any() or events[pair].isna().any().any():
        raise ValueError('invalid event fixture key')
    # Exactly one home fixture against each opponent in a league season.
    if events.duplicated(pair).any() or pairs.duplicated(pair).any():
        raise ValueError('ambiguous club pair')
    result = pairs.merge(events[['matchId','kickoff'] + pair], on=pair, how='outer',
                         suffixes=('_players','_events'), validate='one_to_one', indicator=True)
    if result['_merge'].ne('both').any():
        raise ValueError('unresolved fixture')
    return result.drop(columns='_merge')


def build(root: Path) -> dict:
    manifest = json.loads((root/'manifest.json').read_text())
    records = {r['path']:r for r in manifest['records'] if r['repository'].startswith('imadeddine-belkat/')}
    def read(path):
        r = records[path]; data = (root/'objects'/r['sha256']).read_bytes()
        if digest(data) != r['sha256']:
            raise ValueError('raw checksum mismatch')
        return pd.read_csv(root/'objects'/r['sha256'], low_memory=False)
    report = dict(version='archive-crosswalk-v1', seasons={})
    for path in sorted(records):
        if not path.startswith('pl_stats/_merged/events/20'):
            continue
        season = Path(path).name[:7]
        events = read(path)
        players = read(f'pl_stats/_merged/players_match_stats/{season}_players_match_stats.csv')
        if set(players.season) != {season} or set(events.season) != {season}:
            raise ValueError('season mismatch')
        crosswalk = fixture_crosswalk(players, events)
        out = root/'crosswalk'/season; out.mkdir(parents=True,exist_ok=True)
        crosswalk.to_csv(out/'fixtures.csv',index=False)
        merged = players.merge(crosswalk[['matchId_players','matchId_events','kickoff']],
                               left_on='matchId',right_on='matchId_players',validate='many_to_one')
        merged['official_player_code'] = merged.pl_code
        merged['available_at'] = None
        merged['eligible_predeadline'] = False
        merged['invalid_minutes'] = merged.minutesPlayed.lt(0) | merged.minutesPlayed.gt(90)
        merged['missing_identity'] = merged.official_player_code.isna()
        # Keep unknown minutes unknown; they are not negative appearance observations.
        merged['eligible_observed_minutes_label'] = (~merged.invalid_minutes & ~merged.missing_identity & merged.minutesPlayed.notna())
        merged.to_csv(out/'player_match_observations.csv',index=False)
        report['seasons'][season] = dict(fixtures=len(crosswalk), rows=len(merged),
            missing_identity_rows=int(merged.missing_identity.sum()),
            invalid_minutes_rows=int(merged.invalid_minutes.sum()),
            observed_minutes_label_rows=int(merged.eligible_observed_minutes_label.sum()),
            fixture_source_sha256=records[path]['sha256'],
            players_source_sha256=records[f'pl_stats/_merged/players_match_stats/{season}_players_match_stats.csv']['sha256'],
            fixture_crosswalk_sha256=digest((out/'fixtures.csv').read_bytes()),
            observation_sha256=digest((out/'player_match_observations.csv').read_bytes()))
    (root/'crosswalk-report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--root',required=True,type=Path)
    args=ap.parse_args();print(json.dumps(build(args.root),indent=2))


if __name__=='__main__':
    main()
