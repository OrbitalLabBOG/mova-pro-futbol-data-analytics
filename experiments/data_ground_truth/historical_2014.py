"""Recover an additional FPL season; keep historical IDs and local time explicit."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from experiments.data_ground_truth.raw import digest

# Reviewed against the 20 clubs in the pinned 2014/15 fixture source.
OPPONENT_CODES = dict(ARS=3, AVL=7, BUR=90, CHE=8, CRY=31, EVE=11, HUL=88,
                     LEI=13, LIV=14, MCI=43, MUN=1, NEW=4, QPR=52, SOU=20,
                     TOT=6, STK=110, SUN=56, SWA=80, WBA=35, WHU=21)


def reconcile_2014(weekly: pd.DataFrame, players: pd.DataFrame, fixtures: pd.DataFrame):
    frame = weekly.copy()
    parsed = frame.opp.str.extract(r'^(?P<opponent>[A-Z]{3})\((?P<venue>[HA])\) (?P<own_score>\d+)-(?P<opponent_score>\d+)$')
    if parsed.isna().any().any():
        raise ValueError('unrecognized opponent format')
    frame['opponent_code'] = parsed.opponent.map(OPPONENT_CODES)
    if frame.opponent_code.isna().any():
        raise ValueError('unrecognized opponent code')
    frame['was_home'] = parsed.venue.eq('H')
    local = pd.to_datetime('2000 ' + frame.date, format='%Y %d %b %H:%M', errors='raise')
    frame['match_local_time'] = [d.replace(year=2014 if d.month >= 7 else 2015).isoformat() for d in local]
    # This is a local wall-clock match, not an invented UTC/publication timestamp.
    fixtures = fixtures.copy()
    fixtures['match_local_time'] = pd.to_datetime(fixtures.kickoff, errors='raise').map(lambda d: d.isoformat())
    views = []
    for home in (True, False):
        view = fixtures[['matchId', 'match_local_time']].copy()
        view['opponent_code'] = fixtures['away_team_id' if home else 'home_team_id']
        view['match_team_code'] = fixtures['home_team_id' if home else 'away_team_id']
        view['was_home'] = home
        views.append(view)
    lookup = pd.concat(views, ignore_index=True)
    join = ['match_local_time', 'opponent_code', 'was_home']
    if lookup.duplicated(join).any():
        raise ValueError('ambiguous fixture lookup')
    frame = frame.merge(lookup, on=join, how='left', validate='many_to_one')
    if frame.matchId.isna().any():
        raise ValueError(f'{frame.matchId.isna().sum()} unresolved fixtures')
    if frame.duplicated(['id','matchId']).any():
        raise ValueError('duplicate player fixture labels')
    totals = frame.groupby('id').gw_pts.sum(min_count=1).rename('observed_total')
    totals = players[['id','pts']].merge(totals, on='id', how='outer', validate='one_to_one', indicator=True)
    if (totals['_merge'] != 'both').any() or totals.observed_total.ne(totals.pts).any():
        raise ValueError('season total reconciliation failed')
    if frame.mins.isna().any() or ((frame.mins < 0) | (frame.mins > 90)).any():
        raise ValueError('invalid minutes')
    frame['season'] = '2014-15'
    frame['player_id_namespace'] = 'fpl_2014_15'
    frame['fixture_id_namespace'] = 'pl_archive_events'
    frame['available_at'] = None
    frame['eligible_predeadline'] = False
    # pts/value/pct/team are final-season snapshots: preserve under explicit names.
    frame = frame.rename(columns={'pts':'final_season_points','value':'final_season_value',
                                 'pct':'final_season_ownership','team':'final_season_team'})
    return frame, dict(rows=len(frame), players=int(frame.id.nunique()),
        gameweeks=sorted(int(x) for x in frame.gw.unique()), fixtures=int(frame.matchId.nunique()),
        source_fixture_count=int(fixtures.matchId.nunique()),
        missing_fixture_ids=sorted(int(x) for x in set(fixtures.matchId)-set(frame.matchId)),
        season_points_disagreements=0, duplicate_player_fixture_keys=0,
        double_gameweek_extra_rows=int(frame.duplicated(['id','gw']).sum()),
        temporal_status='local_wall_clock_reconciled_publication_unknown',
        cross_season_identity_status='not_yet_linked_to_official_code')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, required=True)
    ap.add_argument('--archive-root', type=Path, required=True)
    args = ap.parse_args()
    import pyreadr  # optional isolated conversion dependency, never production
    manifest = json.loads((args.root / 'manifest.json').read_text())
    frames, hashes = {}, {}
    for r in manifest['records']:
        if r['path'] not in ('data/season201415.RData', 'data/players201415.RData'):
            continue
        path = args.root / 'objects' / r['sha256']
        if digest(path.read_bytes()) != r['sha256']:
            raise ValueError('checksum mismatch')
        name = Path(r['path']).stem
        frames[name] = pyreadr.read_r(str(path))[name]  # Ignore unrelated R objects.
        hashes[name] = r['sha256']
    archive = json.loads((args.archive_root / 'manifest.json').read_text())
    record = next(r for r in archive['records'] if r['repository'].startswith('imadeddine-belkat/') and r['path']=='pl_stats/_merged/events/2014-15_events_stats.csv')
    path = args.archive_root / 'objects' / record['sha256']
    if digest(path.read_bytes()) != record['sha256']:
        raise ValueError('checksum mismatch')
    frame, report = reconcile_2014(frames['season201415'], frames['players201415'], pd.read_csv(path))
    target = args.root / 'labels-2014-15.csv'
    frame.to_csv(target, index=False)
    report.update(version='fpl-2014-labels-v1', source_hashes=hashes,
                  fixture_source_sha256=record['sha256'], artifact_sha256=digest(target.read_bytes()),
                  pyreadr_version=pyreadr.__version__, pandas_version=pd.__version__)
    (args.root / 'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__ == '__main__':
    main()
