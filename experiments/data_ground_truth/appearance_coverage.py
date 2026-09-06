"""Contrast historical FPL appearances with independently archived match squads."""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

import pandas as pd

from experiments.data_ground_truth.identity_2014 import name_tokens
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked

# Explicit club-name equivalences, not numeric ID equivalences across providers.
CLUB_NAMES={'Birmingham':'Birmingham_City','Blackburn':'Blackburn_Rovers',
    'Bolton':'Bolton_Wanderers','Man City':'Manchester_City','Man Utd':'Manchester_United',
    'Newcastle':'Newcastle_United','Tottenham':'Tottenham_Hotspur',
    'West Brom':'West_Bromwich_Albion','West Ham':'West_Ham_United',
    'Wigan':'Wigan_Athletic','Wolves':'Wolverhampton_Wanderers'}


def compare(matches,fixtures,teams,players,observations,reference_fixtures):
    if set(matches.season)!={11} or set(fixtures.season)!={11} or set(observations.season)!={'2010-11'}:
        raise ValueError('unexpected appearance season')
    clubs=observations[['team_id','team']].drop_duplicates()
    if clubs.team.duplicated().any() or clubs.team_id.duplicated().any():
        raise ValueError('ambiguous reference club')
    names=clubs.set_index('team').team_id.to_dict()
    mapping={}
    for row in teams.to_dict('records'):
        mapping[row['_id']]=names.get(CLUB_NAMES.get(row['name'],row['name'].replace(' ','_')))
    f=fixtures.copy()
    f['home_team_id']=f.team_home_id.map(mapping);f['away_team_id']=f.team_away_id.map(mapping)
    keys=['home_team_id','away_team_id']
    if f[keys].isna().any().any():raise ValueError('unmapped archive club')
    if f.duplicated(keys).any() or reference_fixtures.duplicated(keys).any():raise ValueError('ambiguous fixture pair')
    f=f.merge(reference_fixtures,on=keys,how='outer',validate='one_to_one',indicator=True)
    if f['_merge'].ne('both').any():raise ValueError('unmatched fixture')
    dates=pd.to_datetime(f.datetime,unit='s',utc=True).dt.tz_convert('Europe/London').dt.date
    date_differences=int(dates.ne(pd.to_datetime(f.kickoff).dt.date).sum())
    if date_differences:raise ValueError('fixture date disagreement')
    x=matches.merge(f[['_id','matchId_events','team_home_id','team_away_id']],left_on='fixture_id',right_on='_id',how='left',validate='many_to_one')
    if x.matchId_events.isna().any() or not x.is_home.isin([0,1]).all():raise ValueError('invalid appearance fixture')
    expected_opponent=x.team_away_id.where(x.is_home.eq(1),x.team_home_id)
    if expected_opponent.ne(x.opp_team_id).any():raise ValueError('appearance opponent disagreement')
    x['team_id']=x.team_home_id.where(x.is_home.eq(1),x.team_away_id).map(mapping)
    keys=['matchId_events','team_id']
    a=x.groupby(keys).agg(fpl_rows=('minutes','size'),fpl_minutes=('minutes','sum'))
    p=observations[observations.minutesPlayed.gt(0)].groupby(keys).agg(sport_rows=('minutesPlayed','size'),sport_minutes=('minutesPlayed','sum'))
    coverage=a.join(p,how='outer').reset_index()
    coverage['appearance_count_agrees']=coverage.fpl_rows.eq(coverage.sport_rows)
    lookup={k:g for k,g in observations.groupby(keys)}
    if players._id.duplicated().any():raise ValueError('ambiguous archive player')
    player_names=players.set_index('_id').name
    candidates=[]
    for pid,group in x.groupby('player_fpl_id'):
        tokens=name_tokens(player_names[pid]);sets=[]
        for row in group.itertuples():
            obs=lookup.get((row.matchId_events,row.team_id),observations.iloc[:0])
            sets.append({int(r.playerId) for r in obs.itertuples() if tokens and tokens<=name_tokens(r.playerName)})
        ids=set.intersection(*sets)
        candidates.append(dict(fpl_id=int(pid),source_name=player_names[pid],appearances=len(group),
            candidate_native_player_id=next(iter(ids)) if len(ids)==1 else None,
            candidate_count=len(ids),eligible_identity=False,eligible_training=False))
    candidates=pd.DataFrame(candidates)
    resolved=candidates.candidate_native_player_id.notna()
    report=dict(version='historical-appearance-coverage-v1',season='2010-11',fixtures=len(f),
        fixture_date_disagreements=date_differences,fixture_team_sides=len(coverage),
        matching_appearance_count_sides=int(coverage.appearance_count_agrees.sum()),
        count_disagreements=coverage.loc[~coverage.appearance_count_agrees].to_dict('records'),
        fpl_appearance_rows=len(x),sport_positive_minute_rows=int(observations.minutesPlayed.gt(0).sum()),
        sport_unknown_minute_rows=int(observations.minutesPlayed.isna().sum()),
        unique_candidate_players=int(resolved.sum()),candidate_appearance_rows=int(candidates.loc[resolved,'appearances'].sum()),
        unresolved_candidate_players=int((~resolved).sum()),
        identity_status='name_and_fixture_candidates_only_not_promoted',
        coverage_status='independent_sources_can_both_omit_or_disagree',
        new_complete_seasons=0,eligible_training=False)
    return coverage,candidates,report


def build(sql_root: Path,sport_root: Path,out: Path):
    sql_report=json.loads((sql_root/'report.json').read_text())
    sport_report=json.loads((sport_root/'crosswalk-report.json').read_text())['seasons']['2010-11']
    hashes={}
    def read(path,sha):
        hashes[str(path.name)]=sha
        return pd.read_csv(io.BytesIO(checked(path,sha)))
    tables={n:read(sql_root/(n+'.csv'),sql_report['artifacts'][n]['sha256']) for n in ['player_match','fixture','team','player']}
    observations=read(sport_root/'crosswalk/2010-11/player_match_observations.csv',sport_report['observation_sha256'])
    fixtures=read(sport_root/'crosswalk/2010-11/fixtures.csv',sport_report['fixture_crosswalk_sha256'])
    coverage,candidates,report=compare(tables['player_match'],tables['fixture'],tables['team'],tables['player'],observations,fixtures)
    out.mkdir(parents=True,exist_ok=True)
    for name,frame in [('fixture_team_coverage',coverage),('identity_candidates',candidates)]:
        frame.to_csv(out/(name+'.csv'),index=False)
    report['source_sha256']=hashes
    report['artifacts']={n:digest((out/(n+'.csv')).read_bytes()) for n in ['fixture_team_coverage','identity_candidates']}
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for arg in ['sql-root','sport-root','out']:ap.add_argument('--'+arg,type=Path,required=True)
    args=ap.parse_args();print(json.dumps(build(args.sql_root,args.sport_root,args.out),indent=2))


if __name__=='__main__':main()
