"""Link old FPL appearances without replacing their source minutes or points."""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import re

import pandas as pd

from experiments.data_ground_truth.appearance_coverage import join_appearances
from experiments.data_ground_truth.identity_2014 import name_tokens
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked


def name_matches(short: str,full: str):
    tokens=name_tokens(short)
    if tokens and tokens<=name_tokens(full):return True
    # Archived FPL encodes same-surname players as e.g. Young L or Diouf EH.
    match=re.fullmatch(r'(.+) ([A-Z]{1,3})',short)
    if not match:return False
    surname,initials=match.groups();base=name_tokens(surname)
    full_words=[]
    for word in full.split():
        parts=name_tokens(word)
        if len(parts)!=1:return False
        full_words.append(next(iter(parts)))
    if not base or not base<=set(full_words):return False
    given=[w for w in full_words if w not in base]
    return ''.join(w[0] for w in given)==initials.lower()


def resolve(appearances: pd.DataFrame,players: pd.DataFrame,observations: pd.DataFrame,prior_players: list[dict] | None=None):
    result=appearances.copy()
    result['official_player_code']=pd.Series(pd.NA,index=result.index,dtype='Int64')
    result['identity_verified']=False
    if players._id.duplicated().any():raise ValueError('ambiguous FPL metadata')
    names=players.set_index('_id').name
    if appearances.duplicated(['player_fpl_id','fixture_id']).any():raise ValueError('duplicate FPL appearance')
    if observations.duplicated(['matchId_events','team_id','playerId']).any():raise ValueError('duplicate sports appearance')
    lookup={k:g for k,g in observations.groupby(['matchId_events','team_id'])}
    evidence=[];unresolved=[]
    for pid,group in result.groupby('player_fpl_id'):
        prior={}
        for player in prior_players or []:
            history=[h for h in player['season_history'] if h[0]=='2010/11']
            full=player['first_name']+' '+player['second_name']
            if (len(history)==1 and history[0][1]==group.minutes.sum() and history[0][-1]==group.total.sum()
                and name_matches(names[pid],full)):
                prior[int(player['code'])]=name_tokens(full)
        candidates=[];matched=[]
        for row in group.itertuples():
            obs=lookup.get((row.matchId_events,row.team_id),observations.iloc[:0])
            named=obs.playerName.map(lambda name:name_matches(names[pid],name))
            prior_match=pd.Series([pd.notna(r.official_player_code) and prior.get(int(r.official_player_code))==name_tokens(r.playerName)
                for r in obs.itertuples()],index=obs.index,dtype=bool)
            obs=obs[named & (obs.minutesPlayed.gt(0)|prior_match) & obs.official_player_code.notna()]
            candidates.append(set(int(c) for c in obs.official_player_code));matched.append(obs)
        codes=set.intersection(*candidates)
        prior_supported=(len(codes)==1 and next(iter(codes)) in prior and
            all(name_tokens(n)==prior[next(iter(codes))] for o in matched for n in o.loc[o.official_player_code.eq(next(iter(codes))),'playerName']))
        if len(codes)!=1 or (group.fixture_id.nunique()<2 and not prior_supported):
            unresolved.append(dict(fpl_id=int(pid),name=names[pid],rows=len(group),candidate_count=len(codes),
                reason='not_unique_in_every_played_fixture' if len(codes)!=1 else 'fewer_than_two_played_fixtures'))
            continue
        code=next(iter(codes));witness=pd.concat([o[o.official_player_code.eq(code)] for o in matched])
        if witness.playerId.nunique()!=1 or len({name_tokens(n) for n in witness.playerName})!=1:
            unresolved.append(dict(fpl_id=int(pid),name=names[pid],rows=len(group),reason='conflicting_sports_identity'));continue
        result.loc[group.index,'official_player_code']=code;result.loc[group.index,'identity_verified']=True
        evidence.append(dict(fpl_id=int(pid),source_name=names[pid],official_player_code=code,
            native_player_id=int(witness.iloc[0].playerId),full_name=witness.iloc[0].playerName,
            fixtures=sorted(int(x) for x in group.matchId_events),rows=len(group),
            corroborated_by_later_fpl_season_totals=prior_supported))
    identities=result[['player_fpl_id','official_player_code']].dropna().drop_duplicates()
    if identities.official_player_code.duplicated().any():raise ValueError('cross-FPL identity collision')
    result['eligible_training']=False;result['eligible_predeadline']=False
    report=dict(version='historical-fpl-identity-v1',source_appearance_rows=len(result),
        verified_players=len(evidence),verified_rows=int(result.identity_verified.sum()),
        unresolved_players=len(unresolved),unresolved_rows=int((~result.identity_verified).sum()),
        unresolved=unresolved,new_complete_seasons=0,
        source_outcomes_preserved=result[['minutes','total']].equals(appearances[['minutes','total']]),
        status='linked_appearance_labels_not_complete_eligibility_universe')
    return result,evidence,report


def build(sql_root: Path,sport_root: Path,native_root: Path,later_root: Path,out: Path):
    sql=json.loads((sql_root/'report.json').read_text());native=json.loads((native_root/'report.json').read_text())
    sports=json.loads((sport_root/'crosswalk-report.json').read_text())['seasons']['2010-11']
    hashes={}
    def read(path,sha):
        hashes[path.name]=sha;return pd.read_csv(io.BytesIO(checked(path,sha)))
    tables={n:read(sql_root/(n+'.csv'),sql['artifacts'][n]['sha256']) for n in ['player_match','fixture','team','player']}
    obs=read(native_root/'archive/2010-11/observations.csv',native['seasons']['2010-11']['artifact_sha256'])
    fixtures=read(sport_root/'crosswalk/2010-11/fixtures.csv',sports['fixture_crosswalk_sha256'])
    joined,_,_=join_appearances(tables['player_match'],tables['fixture'],tables['team'],obs,fixtures)
    later_manifest=(later_root/'manifest.json').read_bytes();later=[]
    for record in json.loads(later_manifest)['records']:
        if record['path'].startswith('PlayersInfo/'):
            later.append(json.loads(checked(later_root/'objects'/record['sha256'],record['sha256'])))
    hashes['later_fpl_manifest']=digest(later_manifest)
    linked,evidence,report=resolve(joined,tables['player'],obs,later)
    report['players_corroborated_by_later_fpl_totals']=sum(x['corroborated_by_later_fpl_season_totals'] for x in evidence)
    out.mkdir(parents=True,exist_ok=True);linked.to_csv(out/'appearances.csv',index=False)
    (out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
    report.update(source_sha256=hashes,labels_sha256=digest((out/'appearances.csv').read_bytes()),
        evidence_sha256=digest((out/'evidence.json').read_bytes()))
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for arg in ['sql-root','sport-root','native-root','later-root','out']:ap.add_argument('--'+arg,type=Path,required=True)
    args=ap.parse_args();print(json.dumps(build(args.sql_root,args.sport_root,args.native_root,args.later_root,args.out),indent=2))


if __name__=='__main__':main()
