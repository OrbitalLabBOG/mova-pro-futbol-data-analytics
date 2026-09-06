"""Immutable retrospective FPL labels, verified inputs, explicit temporal partitions."""
from __future__ import annotations

import argparse
import gzip
import io
import json
from pathlib import Path
import tempfile

import pandas as pd

from experiments.data_ground_truth.raw import digest

VERSION = 'fpl-labels-v2'
COMPONENTS = ['goals_scored','assists','clean_sheets','goals_conceded','own_goals',
              'penalties_saved','penalties_missed','yellow_cards','red_cards','saves','bonus','bps']


def checked(path: Path, sha: str) -> bytes:
    data=path.read_bytes()
    if digest(data)!=sha:
        raise ValueError(f'hash mismatch: {path.name}')
    return data


def quarantine_postponed(frame: pd.DataFrame, fixtures: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Remove only zero placeholders superseded by a verified finished fixture."""
    rejected=[]
    duplicates=frame[frame.duplicated(['element','fixture'],keep=False)]
    for (_,fixture), group in duplicates.groupby(['element','fixture']):
        final=fixtures[fixtures.id.eq(fixture)]
        if len(final)!=1 or not final.iloc[0]['finished'] == True:
            raise ValueError('postponement requires unique finished fixture')
        final=final.iloc[0]
        times=pd.to_datetime(group.kickoff_time,utc=True,errors='raise')
        actual=pd.to_datetime(final.kickoff_time,utc=True,errors='raise')
        keep=group.gw.eq(final.event) & times.eq(actual)
        if keep.sum()!=1:
            raise ValueError('postponement requires unique actual observation')
        stale=group.loc[~keep]
        outcomes=['minutes','total_points']+[c for c in COMPONENTS if c in stale]
        zero=stale[outcomes].apply(pd.to_numeric,errors='raise').eq(0).all(axis=1)
        if not zero.all() or not times.loc[~keep].lt(actual).all():
            raise ValueError('conflicting postponed observation')
        rejected.extend(stale.index.tolist())
    quarantine=frame.loc[rejected].copy()
    quarantine['exclusion_reason']='superseded_zero_postponement_placeholder'
    return frame.drop(index=rejected).copy(),quarantine


def normalize(frame: pd.DataFrame, season: str, historical: bool) -> pd.DataFrame:
    source=frame.copy()
    if historical:
        source=source.rename(columns={'id':'element','matchId':'fixture','mins':'minutes','gw_pts':'total_points',
            'goals':'goals_scored','cs':'clean_sheets','ga':'goals_conceded','og':'own_goals',
            'pens_svd':'penalties_saved','pens_msd':'penalties_missed','yel':'yellow_cards','red':'red_cards'})
    result=source[['element','fixture','gw','minutes','total_points','official_player_code']].copy()
    result['season']=season
    result['fixture_namespace']='pl_archive_events' if historical else 'fpl_season_fixture'
    for column in ['element','fixture','gw','minutes','total_points']:
        values=pd.to_numeric(result[column],errors='raise')
        if values.isna().any() or values.ne(values.round()).any():
            raise ValueError('invalid integral label or key')
        result[column]=values.astype('int64')
    if result.minutes.lt(0).any() or result.minutes.gt(90).any() or result.gw.lt(1).any():
        raise ValueError('invalid label range')
    codes=pd.to_numeric(result.official_player_code,errors='raise').astype('Int64')
    if (codes.dropna()<=0).any():
        raise ValueError('invalid official player code')
    result['official_player_code']=codes
    result['identity_key']=[f'opta:{int(code)}' if pd.notna(code) else f'fpl:{season}:{int(element)}'
                            for code,element in zip(codes,result.element)]
    if result.duplicated(['element','fixture']).any():
        raise ValueError('duplicate player fixture')
    for component in COMPONENTS:
        result[component]=pd.to_numeric(source[component],errors='raise') if component in source else pd.NA
    result['event_time_utc']=source['kickoff_time'] if not historical else pd.NA
    result['event_local_time']=source['match_local_time'] if historical else pd.NA
    result['available_at']=pd.NA
    result['eligible_predeadline']=False
    result['source']='fantasysocceR' if historical else 'vaastav_fpl'
    # No final-season price, ownership, club, total or name enters this label contract.
    return result.sort_values(['gw','element','fixture']).reset_index(drop=True)


def verify(package: Path) -> dict:
    manifest=json.loads((package/'manifest.json').read_text())
    descriptor={k:v for k,v in manifest.items() if k!='dataset_id'}
    if digest(json.dumps(descriptor,sort_keys=True,separators=(',',':')).encode())!=manifest['dataset_id']:
        raise ValueError('manifest identity mismatch')
    rows=0
    for entry in manifest['partitions']:
        name=entry['file']
        if Path(name).name!=name:
            raise ValueError('unsafe partition path')
        payload=checked(package/name,entry['sha256'])
        frame=pd.read_csv(io.BytesIO(gzip.decompress(payload)))
        if len(frame)!=entry['rows'] or set(frame.season)!={entry['season']}:
            raise ValueError('partition content mismatch')
        if frame.duplicated(['element','fixture']).any():
            raise ValueError('duplicate labels')
        if frame.eligible_predeadline.any() or frame.available_at.notna().any():
            raise ValueError('unproven temporal availability')
        rows+=len(frame)
    for entry in manifest.get('quarantines',[]):
        if Path(entry['file']).name!=entry['file']:
            raise ValueError('unsafe quarantine path')
        frame=pd.read_csv(io.BytesIO(gzip.decompress(checked(package/entry['file'],entry['sha256']))))
        if len(frame)!=entry['rows'] or not frame.exclusion_reason.eq(entry['reason']).all():
            raise ValueError('quarantine content mismatch')
    if rows!=manifest['rows']:
        raise ValueError('row count mismatch')
    return manifest


def load_partition(package: Path, split: str) -> pd.DataFrame:
    if split not in {'train','validation','evaluation'}:
        raise ValueError('unknown split')
    manifest=verify(package)
    parts=[pd.read_csv(package/e['file'],compression='gzip') for e in manifest['partitions'] if e['split']==split]
    return pd.concat(parts,ignore_index=True) if parts else pd.DataFrame()


def build(recent_root: Path, old_root: Path, output: Path, identity_root: Path | None = None, season_2015_root: Path | None = None) -> Path:
    recent_manifest=json.loads((recent_root/'labels-manifest.json').read_text())
    identity_root=identity_root or old_root/'identity'
    old_manifest=json.loads((identity_root/'report.json').read_text())
    inputs=[];frames=[];quarantines=[]
    raw_records=json.loads((recent_root/'manifest.json').read_text())['records']
    for season,info in sorted(recent_manifest['seasons'].items()):
        data=checked(recent_root/'labels'/f'{season}.csv',info['artifact_sha256'])
        inputs.append(dict(season=season,sha256=info['artifact_sha256'],role='official_fpl_observed_labels'))
        frame=pd.read_csv(io.BytesIO(data))
        if frame.duplicated(['element','fixture']).any():
            records=[r for r in raw_records if r['repository'].startswith('vaastav/') and r['path']==f'data/{season}/fixtures.csv']
            if len(records)!=1:
                raise ValueError('missing postponement fixture evidence')
            record=records[0]
            evidence=checked(recent_root/'objects'/record['sha256'],record['sha256'])
            inputs.append(dict(season=season,sha256=record['sha256'],role='finished_fixture_postponement_evidence'))
            frame,quarantine=quarantine_postponed(frame,pd.read_csv(io.BytesIO(evidence)))
            quarantines.append((season,quarantine))
        frames.append((season,normalize(frame,season,False)))
    data=checked(identity_root/'labels.csv',old_manifest['labels_sha256'])
    inputs.append(dict(season='2014-15',sha256=old_manifest['labels_sha256'],role='reconciled_historical_fpl_labels'))
    frames.append(('2014-15',normalize(pd.read_csv(io.BytesIO(data)),'2014-15',True)))
    if season_2015_root is not None:
        history=json.loads((season_2015_root/'report.json').read_text())
        if history['fixtures']!=380 or history['missing_fixture_ids'] or history['season_points_disagreements']:
            raise ValueError('2015 closed season gate not satisfied')
        data=checked(season_2015_root/'labels.csv',history['labels_sha256'])
        normalized=normalize(pd.read_csv(io.BytesIO(data)),'2015-16',True)
        if normalized.fixture.nunique()!=380 or set(normalized.gw)!=set(range(1,39)) or len(normalized)!=history['rows']:
            raise ValueError('2015 labels contradict coverage report')
        normalized['source']='mvbfontes_fpl_archive'
        inputs.append(dict(season='2015-16',sha256=history['labels_sha256'],role='complete_historical_fpl_labels'))
        frames.append(('2015-16',normalized))
    # No claim of unseen test data: 2025/26 has already been used in earlier research.
    partitions=[];payloads={}
    for season,frame in sorted(frames):
        split='evaluation' if season=='2025-26' else 'validation' if season=='2024-25' else 'train'
        if season>'2025-26':
            raise ValueError('unreviewed season partition')
        payload=gzip.compress(frame.to_csv(index=False).encode(),mtime=0)
        filename=season+'.csv.gz';payloads[filename]=payload
        partitions.append(dict(season=season,split=split,file=filename,rows=len(frame),
            sha256=digest(payload),official_identity_rows=int(frame.official_player_code.notna().sum()),
            season_scoped_identity_rows=int(frame.official_player_code.isna().sum())))
    exclusions=[]
    for season,frame in quarantines:
        filename=season+'-quarantine.csv.gz'
        payload=gzip.compress(frame.to_csv(index=False).encode(),mtime=0)
        payloads[filename]=payload
        exclusions.append(dict(season=season,file=filename,rows=len(frame),sha256=digest(payload),
            reason='superseded_zero_postponement_placeholder'))
    manifest=dict(schema_version=1,version=VERSION,implementation_sha256=digest(Path(__file__).read_bytes()),
        pandas_version=pd.__version__,inputs=sorted(inputs,key=lambda x:x['season']),
        quarantines=exclusions,partitions=partitions,rows=sum(p['rows'] for p in partitions),
        purpose='retrospective_label_training_not_predeadline_replay',
        evaluation_status='historical_previously_used_not_unseen',
        missing_complete_seasons=[] if season_2015_root else ['2015-16'],
        partial_seasons_excluded=[] if season_2015_root else ['2015-16'],unknown_available_at=True,
        excluded=['final_season_snapshots','prices','ownership','official_xp','pl_minutes_substitution'])
    manifest['dataset_id']=digest(json.dumps(manifest,sort_keys=True,separators=(',',':')).encode())
    target=output/manifest['dataset_id'];output.mkdir(parents=True,exist_ok=True)
    if target.exists():
        verify(target)
        return target
    with tempfile.TemporaryDirectory(dir=output) as temporary:
        staging=Path(temporary)/'package';staging.mkdir()
        for name,payload in payloads.items():
            (staging/name).write_bytes(payload)
        (staging/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        verify(staging)
        staging.rename(target)
    return target


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--recent-root',type=Path,required=True);ap.add_argument('--old-root',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--identity-root',type=Path)
    ap.add_argument('--season-2015-root',type=Path)
    args=ap.parse_args();path=build(args.recent_root,args.old_root,args.output,args.identity_root,args.season_2015_root)
    manifest=verify(path)
    print(json.dumps(dict(path=str(path),dataset_id=manifest['dataset_id'],rows=manifest['rows'],
        partitions=[{k:p[k] for k in ['season','split','rows']} for p in manifest['partitions']]),indent=2))


if __name__=='__main__':
    main()
