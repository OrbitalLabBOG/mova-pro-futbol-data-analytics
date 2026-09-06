"""Recover retrospective identities using native IDs and repeated full-name witnesses."""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

import pandas as pd

from experiments.data_ground_truth.identity_2014 import name_tokens
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked


def propagate(frame: pd.DataFrame):
    result=frame.copy()
    known=result[result.official_player_code.notna()]
    conflicts=known.groupby('playerId').official_player_code.nunique()
    if conflicts.gt(1).any():raise ValueError('native player namespace code conflict')
    witnesses={}
    for row in known.itertuples():
        key=(int(row.playerId),name_tokens(row.playerName))
        witnesses.setdefault(key,dict(code=int(row.official_player_code),fixtures=set()))['fixtures'].add((row.season,int(row.matchId_events)))
    result['native_identity_recovered']=False
    evidence=[]
    missing=result[result.official_player_code.isna()]
    for (season,pid,name),group in missing.groupby(['season','playerId','playerName']):
        witness=witnesses.get((int(pid),name_tokens(name)))
        if not witness or len(witness['fixtures'])<2:continue
        result.loc[group.index,'official_player_code']=witness['code']
        result.loc[group.index,'native_identity_recovered']=True
        evidence.append(dict(season=season,native_player_id=int(pid),full_name=name,official_player_code=witness['code'],
            added_rows=len(group),witness_fixtures=[list(x) for x in sorted(witness['fixtures'])]))
    result['missing_identity']=result.official_player_code.isna()
    result['eligible_observed_minutes_label']=result.official_player_code.notna() & result.minutesPlayed.between(0,90)
    # Retrospective identity is never proof that a feature was known at decision time.
    result['eligible_predeadline']=False
    return result,evidence


def build(registry_root: Path,out: Path):
    manifest_bytes=(registry_root/'report.json').read_bytes();manifest=json.loads(manifest_bytes)
    frames=[]
    for season,info in sorted(manifest['seasons'].items()):
        raw=checked(registry_root/'archive'/season/'observations.csv',info['artifact_sha256'])
        f=pd.read_csv(io.BytesIO(raw))
        if set(f.season)!={season}:raise ValueError('registry season mismatch')
        frames.append(f)
    original=pd.concat(frames,ignore_index=True)
    linked,evidence=propagate(original)
    seasons={}
    for season,f in linked.groupby('season'):
        dest=out/'archive'/season;dest.mkdir(parents=True,exist_ok=True)
        f.to_csv(dest/'observations.csv',index=False)
        seasons[season]=dict(rows=len(f),added_identity_rows=int(f.native_identity_recovered.sum()),
            missing_identity_rows=int(f.missing_identity.sum()),eligible_observed_minutes_rows=int(f.eligible_observed_minutes_label.sum()),
            artifact_sha256=digest((dest/'observations.csv').read_bytes()),source_sha256=manifest['seasons'][season]['artifact_sha256'])
    out.mkdir(parents=True,exist_ok=True)
    evidence_path=out/'evidence.json';evidence_path.write_text(json.dumps(evidence,indent=2)+'\n')
    report=dict(version='native-identity-v1',seasons=seasons,source_manifest_sha256=digest(manifest_bytes),
        evidence_sha256=digest(evidence_path.read_bytes()),added_identity_rows=int(linked.native_identity_recovered.sum()),
        missing_identity_rows=int(linked.missing_identity.sum()),
        added_minutes_labels=int((linked.native_identity_recovered & linked.eligible_observed_minutes_label).sum()),
        eligible_observed_minutes_rows=int(linked.eligible_observed_minutes_label.sum()),
        source_identity_preserved=original.source_official_player_code.equals(linked.source_official_player_code),
        status='retrospective_identity_not_predeadline_features',new_complete_seasons=0)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--registry-root',type=Path,required=True);ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args();print(json.dumps(build(args.registry_root,args.out),indent=2))


if __name__=='__main__':main()
