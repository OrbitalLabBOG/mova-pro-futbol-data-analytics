"""Corroborate retrospective identity with full-name registries and match evidence."""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

import pandas as pd

from experiments.data_ground_truth.identity_2014 import name_tokens
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked


def variants(name: str) -> set[frozenset]:
    # Đ/đ may be rendered D/d or Dj/dj in Latin football archives. No edit-distance matching.
    return {name_tokens(name),name_tokens(name.replace('Đ','Dj').replace('đ','dj'))}


def link_archive(observations: pd.DataFrame,squads: pd.DataFrame):
    catalog={}
    for row in squads.itertuples():
        for tokens in variants(row.displayName):
            catalog.setdefault((row.team_id,tokens),set()).add(int(row.playerId))
    result=observations.copy();result['source_official_player_code']=result.official_player_code
    result['registry_code']=pd.Series(pd.NA,index=result.index,dtype='Int64')
    validated=0;filled=0
    for (team,_,name),group in result.groupby(['team_id','playerId','playerName']):
        codes=set().union(*(catalog.get((team,t),set()) for t in variants(name)))
        if len(codes)!=1:
            continue
        code=next(iter(codes));known=group.official_player_code.dropna()
        if not known.eq(code).all():
            raise ValueError('archive registry code conflict')
        result.loc[group.index,'registry_code']=code
        validated+=len(known)
        absent=group.index[group.official_player_code.isna()]
        result.loc[absent,'official_player_code']=code;filled+=len(absent)
    result['missing_identity']=result.official_player_code.isna()
    result['eligible_observed_minutes_label']=result.official_player_code.notna() & result.minutesPlayed.between(0,90)
    return result,dict(validated_existing_rows=validated,added_identity_rows=filled,
        missing_identity_rows=int(result.missing_identity.sum()),
        eligible_observed_minutes_rows=int(result.eligible_observed_minutes_label.sum()))


def reconcile_labels(labels: pd.DataFrame,observations: pd.DataFrame,old_players: pd.DataFrame,next_players: list[dict]):
    result=labels.copy();result['source_official_player_code']=result.official_player_code
    aliases=[];evidence=[];validated=0
    # A changed code needs direct full-name metadata from BOTH FPL archives, same club,
    # prior-season minutes/points, and the new code in the actual played fixtures.
    old_meta=old_players.set_index('id')
    if not old_meta.index.is_unique:
        raise ValueError('ambiguous old player metadata')
    for element,group in result.groupby('id'):
        played=group[group.mins.gt(0)]
        if played.empty:
            continue
        tokens=variants(group.iloc[0]['name'])
        prior_codes=set()
        for player in next_players:
            history=[h for h in player['season_history'] if h[0]=='2014/15']
            if (variants(player['web_name']) & tokens and player['team_code'] in set(group.match_team_code)
                and len(history)==1 and history[0][1]==group.mins.sum() and history[0][-1]==group.gw_pts.sum()):
                prior_codes.add(int(player['code']))
        candidate_sets=[]
        for row in played.itertuples():
            obs=observations[observations.matchId_events.eq(row.matchId) & observations.team_id.eq(row.match_team_code)
                & observations.minutesPlayed.gt(0)
                & (observations.registry_code.notna() | observations.official_player_code.isin(prior_codes))]
            obs=obs.loc[obs.playerName.map(lambda n:any(a<=b for a in tokens for b in variants(n))).astype(bool)]
            candidate_sets.append(set(int(c) for c in obs.official_player_code.dropna()))
        codes=set.intersection(*candidate_sets)
        if len(codes)!=1:
            continue
        code=next(iter(codes));known=group.official_player_code.dropna()
        if len(known) and not known.eq(code).all():
            if element not in old_meta.index:
                raise ValueError('code change without old metadata')
            old=old_meta.loc[element];fullname=variants(str(old.first_name)+' '+str(old.second_name))
            prior=[]
            for player in next_players:
                history=[h for h in player['season_history'] if h[0]=='2014/15']
                if (player['code']==code and fullname & variants(player['first_name']+' '+player['second_name'])
                    and player['team_code'] in set(group.match_team_code) and len(history)==1
                    and history[0][1]==group.mins.sum() and history[0][-1]==group.gw_pts.sum()
                    and old.code==known.iloc[0]):
                    prior.append(player)
            if len(prior)!=1:
                raise ValueError('unverified historical code alias')
            aliases.append(dict(element=int(element),source_code=int(known.iloc[0]),canonical_code=code,
                evidence='two_fpl_fullnames_same_club_prior_totals_and_played_fixture'))
            result.loc[group.index,'official_player_code']=code
            result.loc[group.index,'identity_status']='verified_historical_code_alias'
        elif known.empty:
            result.loc[group.index,'official_player_code']=code
            result.loc[group.index,'identity_status']='corroborated_all_played_fixtures'
            evidence.append(dict(element=int(element),official_player_code=code,played_fixture_witnesses=len(played),
                corroboration='prior_fpl_totals' if code in prior_codes else 'full_name_club_registry'))
        else:
            validated+=1
    identities=result[['id','official_player_code']].dropna().drop_duplicates()
    if identities.official_player_code.duplicated().any() or identities.id.duplicated().any():
        raise ValueError('cross-player identity collision')
    played=result.mins.gt(0);resolved=result.official_player_code.notna()
    return result,dict(validated_existing_players=validated,added_players=len(evidence),
        added_identity_rows=int((labels.official_player_code.isna() & resolved).sum()),
        aliases=aliases,evidence=evidence,resolved_players=int(identities.id.nunique()),
        unresolved_players=int(result.loc[~resolved,'id'].nunique()),resolved_rows=int(resolved.sum()),
        played_rows=int(played.sum()),resolved_played_rows=int((played & resolved).sum()))


def build(archive_root: Path,snapshot_root: Path,season_2015_root: Path,output: Path):
    manifest_bytes=(archive_root/'manifest.json').read_bytes();manifest=json.loads(manifest_bytes)
    crosswalk=json.loads((archive_root/'crosswalk-report.json').read_text())
    seasons={};linked={}
    for season,info in sorted(crosswalk['seasons'].items()):
        squads=[];hashes=[]
        for record in manifest['records']:
            if '/squad/' in record['path'] and Path(record['path']).name==f'{season}_squad.csv':
                data=checked(archive_root/'objects'/record['sha256'],record['sha256'])
                frame=pd.read_csv(io.BytesIO(data));frame['team_id']=int(record['path'].split('/')[1].rsplit('_',1)[1])
                squads.append(frame);hashes.append(record['sha256'])
        data=checked(archive_root/'crosswalk'/season/'player_match_observations.csv',info['observation_sha256'])
        frame,quality=link_archive(pd.read_csv(io.BytesIO(data)),pd.concat(squads,ignore_index=True))
        if not quality['validated_existing_rows']:
            raise ValueError('unverified squad namespace')
        dest=output/'archive'/season;dest.mkdir(parents=True,exist_ok=True)
        frame.to_csv(dest/'observations.csv',index=False)
        quality.update(source_sha256=info['observation_sha256'],squad_sha256=sorted(hashes),
            artifact_sha256=digest((dest/'observations.csv').read_bytes()))
        seasons[season]=quality
        if season=='2014-15':linked[season]=frame
    prior=json.loads((snapshot_root/'identity/report.json').read_text())
    labels=pd.read_csv(io.BytesIO(checked(snapshot_root/'identity/labels.csv',prior['labels_sha256'])))
    snapshot=json.loads((snapshot_root/'manifest.json').read_text())
    rec=next(r for r in snapshot['records'] if r['path']=='Data/dec15_players.csv')
    old=pd.read_csv(io.BytesIO(checked(snapshot_root/'objects'/rec['sha256'],rec['sha256'])))
    newer_manifest=(season_2015_root/'manifest.json').read_bytes();newer=[]
    for record in json.loads(newer_manifest)['records']:
        if record['path'].startswith('PlayersInfo/'):
            newer.append(json.loads(checked(season_2015_root/'objects'/record['sha256'],record['sha256'])))
    labels,identity=reconcile_labels(labels,linked['2014-15'],old,newer)
    dest=output/'identity';dest.mkdir(parents=True,exist_ok=True)
    labels.to_csv(dest/'labels.csv',index=False)
    identity.update(labels_sha256=digest((dest/'labels.csv').read_bytes()),prior_labels_sha256=prior['labels_sha256'],
        old_snapshot_sha256=rec['sha256'],newer_manifest_sha256=digest(newer_manifest),
        observation_sha256=seasons['2014-15']['artifact_sha256'])
    (dest/'report.json').write_text(json.dumps(identity,indent=2)+'\n')
    report=dict(version='identity-registry-v1',seasons=seasons,identity_2014=identity,
        added_archive_identity_rows=sum(s['added_identity_rows'] for s in seasons.values()),
        missing_archive_identity_rows=sum(s['missing_identity_rows'] for s in seasons.values()),
        validated_archive_rows=sum(s['validated_existing_rows'] for s in seasons.values()),
        eligible_archive_minutes_rows=sum(s['eligible_observed_minutes_rows'] for s in seasons.values()))
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for arg in ['archive-root','snapshot-root','season-2015-root','output']:
        ap.add_argument('--'+arg,type=Path,required=True)
    args=ap.parse_args();print(json.dumps(build(args.archive_root,args.snapshot_root,args.season_2015_root,args.output),indent=2))


if __name__=='__main__':
    main()
