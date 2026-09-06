"""Reconcile archived BSON player snapshots with the complete 2015/16 labels."""
from __future__ import annotations

import argparse
from collections import Counter
import io
import json
from pathlib import Path

import pandas as pd

from experiments.data_ground_truth.training_dataset import checked


def flatten(players: list[dict]):
    rows=[];metadata=[]
    for player in players:
        metadata.append(dict(id=int(player['id']),official_player_code=int(player['code']),snapshot_points=int(player['total_points'])))
        history=player['fixture_history']
        if isinstance(history,dict):
            items=[]
            for row in history['all']:
                if len(row)!=20:raise ValueError('unknown BSON history schema')
                items.append(dict(date=row[0],gameweek=row[1],opponent_result=row[2],mins_played=row[3],points=row[19]))
            history=items
        for item in history:
            rows.append(dict(id=int(player['id']),date=item['date'],gw=item['gameweek'],opp=item['opponent_result'],
                mins=item['mins_played'],gw_pts=item['points']))
    metadata=pd.DataFrame(metadata)
    if metadata.id.duplicated().any() or metadata.official_player_code.duplicated().any():
        raise ValueError('ambiguous BSON player identity')
    return pd.DataFrame(rows),metadata


def reconcile(players: list[dict],reference: pd.DataFrame):
    """Quarantine whole player records on conflict; never repair source identities."""
    ids=Counter(int(p['id']) for p in players)
    codes=Counter(int(p['code']) for p in players)
    keys=['id','date','opp']
    accepted=[];rejected=[];pending_count=0;raw_count=0
    for index,player in enumerate(players):
        frame,metadata=flatten([player]);raw_count+=len(frame)
        reasons=[]
        if ids[int(player['id'])]>1 or codes[int(player['code'])]>1:
            reasons.append('ambiguous_identity')
        if frame.empty:
            rejected.append(dict(record_index=index,id=int(player['id']),rows=0,reasons=['empty_history']))
            continue
        frame=frame.merge(metadata,on='id',validate='many_to_one')
        pending=~frame.opp.str.fullmatch(r'[A-Z]{3}\([HA]\) \d+-\d+')
        if (pending & (frame.mins.ne(0)|frame.gw_pts.ne(0))).any():
            reasons.append('unscored_nonzero_outcome')
        observed=frame.loc[~pending].copy()
        if observed.duplicated(keys).any():reasons.append('duplicate_observation')
        joined=observed.merge(reference[keys+['matchId','mins','gw_pts','gw','official_player_code']],on=keys,
            how='left',suffixes=('','_reference'),indicator=True,validate='many_to_one')
        if joined['_merge'].ne('both').any():reasons.append('unmatched_observations')
        matched=joined.loc[joined['_merge'].eq('both')]
        for c in ['mins','gw_pts','gw','official_player_code']:
            if matched[c].ne(matched[c+'_reference']).any():reasons.append(c+'_disagreement')
        if observed.gw_pts.sum()!=int(player['total_points']):reasons.append('snapshot_total_disagreement')
        if reasons:
            rejected.append(dict(record_index=index,id=int(player['id']),rows=len(frame),reasons=reasons))
        else:
            pending_count+=int(pending.sum());accepted.append(joined)
    valid=pd.concat(accepted,ignore_index=True) if accepted else pd.DataFrame()
    return dict(players=len(players),raw_rows=raw_count,corroborated_players=len(accepted),
        corroborated_rows=len(valid),fixtures=int(valid.matchId.nunique()) if len(valid) else 0,
        gameweeks=sorted(int(x) for x in valid.gw.unique()) if len(valid) else [],
        quarantined_unscored_rows=pending_count,quarantined_player_records=rejected,
        quarantined_conflict_rows=sum(r['rows'] for r in rejected),
        season='2015-16',eligible_training=False,
        status='corroborating_partial_snapshot_not_new_season')


def build(root: Path,season_root: Path):
    import bson  # Optional isolated pymongo dependency; no MongoDB connection.
    import pymongo
    manifest=json.loads((root/'manifest.json').read_text())
    reference_report=json.loads((season_root/'report.json').read_text())
    reference=pd.read_csv(io.BytesIO(checked(season_root/'labels.csv',reference_report['labels_sha256'])))
    snapshots={}
    for record in manifest['records']:
        if not record['path'].endswith('.bson'):continue
        players=bson.decode_all(checked(root/'objects'/record['sha256'],record['sha256']))
        report=reconcile(players,reference)
        report['sha256']=record['sha256']
        # ObjectId timestamp is a source assertion, never verified publication time.
        times=[p['_id'].generation_time.isoformat() for p in players]
        report['claimed_record_time_min']=min(times);report['claimed_record_time_max']=max(times)
        snapshots[record['path']]=report
    result=dict(version='bson-archive-audit-v1',pymongo_version=pymongo.__version__,snapshots=snapshots,
        reference_sha256=reference_report['labels_sha256'],new_complete_seasons=0,
        available_at=None,eligible_predeadline=False,
        temporal_status='objectid_clock_is_unverified_source_claim')
    (root/'report.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--root',type=Path,required=True)
    ap.add_argument('--season-root',type=Path,required=True)
    args=ap.parse_args();print(json.dumps(build(args.root,args.season_root),indent=2))


if __name__=='__main__':main()
