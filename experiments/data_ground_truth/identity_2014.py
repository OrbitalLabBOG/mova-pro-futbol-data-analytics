"""Evidence-based historical identity linking, with unresolved rows preserved."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import unicodedata

import pandas as pd

from experiments.data_ground_truth.raw import digest


def name_tokens(value: str) -> frozenset[str]:
    value = str(value).lower().translate(str.maketrans({'ð':'d','ø':'o','ł':'l','đ':'d','ß':'ss'}))
    value = unicodedata.normalize('NFKD', value).encode('ascii','ignore').decode()
    return frozenset(re.findall('[a-z]+', value))


def resolve(labels: pd.DataFrame, observations: pd.DataFrame):
    left = labels.copy(); right = observations.copy()
    left['name_tokens'] = left.name.map(name_tokens)
    right['full_tokens'] = right.playerName.map(name_tokens)
    pairs = left[['id','matchId','match_team_code','mins','name_tokens']].merge(
        right[['matchId_events','team_id','official_player_code','minutesPlayed','full_tokens']],
        left_on=['matchId','match_team_code'], right_on=['matchId_events','team_id'])
    pairs = pairs.loc[pairs.official_player_code.notna() & pairs.mins.gt(0) & pairs.minutesPlayed.gt(0)]
    named = pd.Series([bool(a) and a <= b for a,b in zip(pairs.name_tokens,pairs.full_tokens)], index=pairs.index, dtype=bool)
    pairs = pairs.loc[named]
    evidence = pairs.groupby(['id','official_player_code']).agg(
        matching_fixtures=('matchId','nunique')).reset_index()
    # Two distinct played fixtures AND a single candidate code. Never pick the top score.
    candidates = evidence.groupby('id').official_player_code.nunique()
    accepted = evidence.loc[evidence.id.isin(candidates[candidates.eq(1)].index) & evidence.matching_fixtures.ge(2)]
    # Do not assign one official player to several historical IDs.
    accepted = accepted.loc[~accepted.official_player_code.duplicated(keep=False)]
    linked = labels.merge(accepted, on='id', how='left', validate='many_to_one')
    linked['identity_status'] = linked.official_player_code.notna().map({True:'resolved_structural_witnesses', False:'unresolved'})
    unresolved = linked.loc[linked.official_player_code.isna()].groupby(['id','name','pos']).agg(rows=('gw_pts','size'),minutes=('mins','sum')).reset_index()
    witnesses = pairs.merge(accepted[['id','official_player_code']],on=['id','official_player_code'],validate='many_to_one')
    report = dict(rows=len(linked), players=int(linked.id.nunique()),
        resolved_players=int(accepted.id.nunique()), resolved_rows=int(linked.official_player_code.notna().sum()),
        played_rows=int(linked.mins.gt(0).sum()),
        resolved_played_rows=int((linked.mins.gt(0)&linked.official_player_code.notna()).sum()),
        minutes_disagreement_witness_rows=int(witnesses.mins.ne(witnesses.minutesPlayed).sum()),
        identity_method='exact_name_tokens_club_fixture_two_played_witnesses_unique_code',
        minute_values_policy='preserve_each_source_no_rounding_or_replacement')
    return linked, unresolved, accepted, report


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--root',type=Path,required=True);ap.add_argument('--archive-root',type=Path,required=True)
    args=ap.parse_args()
    source=args.root/'labels-2014-15.csv'; report_path=args.root/'report.json'
    if digest(source.read_bytes())!=json.loads(report_path.read_text())['artifact_sha256']:
        raise ValueError('label hash mismatch')
    observation=args.archive_root/'crosswalk/2014-15/player_match_observations.csv'
    if digest(observation.read_bytes()) != json.loads((args.archive_root/'crosswalk-report.json').read_text())['seasons']['2014-15']['observation_sha256']:
        raise ValueError('observation hash mismatch')
    linked,unresolved,evidence,report=resolve(pd.read_csv(source),pd.read_csv(observation,low_memory=False))
    out=args.root/'identity';out.mkdir(exist_ok=True)
    for name,frame in [('labels',linked),('unresolved',unresolved),('evidence',evidence)]:
        target=out/(name+'.csv');frame.to_csv(target,index=False);report[name+'_sha256']=digest(target.read_bytes())
    report.update(source_label_sha256=digest(source.read_bytes()), source_observation_sha256=digest(observation.read_bytes()))
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
