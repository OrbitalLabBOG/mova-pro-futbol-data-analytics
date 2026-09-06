"""Compare archived roster signatures and player codes to two pinned GT seasons."""
from __future__ import annotations
import argparse
from collections import Counter
import io
import json
from pathlib import Path
import pandas as pd
from experiments.data_ground_truth.profile_history_reconciliation import GT_ID,GT_MANIFEST,FIXTURES
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked,verify


def candidate_season(codes,reference_sets):
    matches=[season for season,known in reference_sets.items() if set(codes)==set(known)]
    return matches[0] if len(matches)==1 else None


def compare(states,gt):
    identities=gt[['element','official_player_code']].drop_duplicates()
    if identities.element.duplicated().any():
        raise ValueError('ambiguous GT player identity')
    paired=states.merge(identities,left_on='id',right_on='element',how='left',validate='many_to_one')
    paired['identity_status']='code_pair_matches_reference'
    paired.loc[paired.code.ne(paired.official_player_code),'identity_status']='code_mismatch'
    paired.loc[paired.official_player_code.isna(),'identity_status']='missing_reference_id'
    return paired


def build(base,out):
    parent=json.loads(Path(__file__).with_name('results-g108.json').read_text())
    root=base/'geek-audit-g108-v1';checked(root/'report.json',parent['report_sha256'])
    inventory=json.loads(checked(root/'snapshots.json',parent['audit']['artifacts']['snapshots.json']))
    states=pd.read_csv(io.BytesIO(checked(root/'player_states.csv',parent['audit']['artifacts']['player_states.csv'])))
    reference_sets={}
    for year,sha in FIXTURES.items():
        fixtures=pd.read_csv(io.BytesIO(checked(base/'raw-history-v2/objects'/sha,sha)))
        reference_sets[f'{year}-{str(year+1)[-2:]}']=set(fixtures.home_team_id)|set(fixtures.away_team_id)
    package=base/'training-datasets'/GT_ID;checked(package/'manifest.json',GT_MANIFEST);manifest=verify(package)
    gt={p['season']:pd.read_csv(package/p['file']) for p in manifest['partitions'] if p['season'] in reference_sets}
    entries=[];conflicts=[];counts=Counter();per_season={}
    for snapshot in inventory:
        if snapshot['status']!='decoded':
            continue
        subset=states.loc[states.source_revision.eq(snapshot['revision'])]
        if len(subset)!=snapshot['players']:
            raise ValueError('snapshot state count mismatch')
        season=candidate_season(snapshot['source_team_codes'],reference_sets)
        entry={k:snapshot[k] for k in ('revision','sha256','author_date','players')}
        entry.update(candidate_season=season,season_verified_from_source=False,eligible_predeadline=False)
        if season is None:
            entries.append(entry|dict(status='ambiguous_or_unknown_roster'));continue
        paired=compare(subset,gt[season]);c=Counter(paired.identity_status);counts.update(c)
        per_season.setdefault(season,Counter()).update(c)
        bad=paired.loc[paired.identity_status.ne('code_pair_matches_reference')].copy()
        bad['candidate_season']=season;bad['author_date']=snapshot['author_date']
        conflicts.append(bad);entry.update(status='roster_candidate',identity_counts=dict(c));entries.append(entry)
    bad=pd.concat(conflicts,ignore_index=True) if conflicts else pd.DataFrame()
    out.mkdir(parents=True,exist_ok=True)
    (out/'snapshots.json').write_text(json.dumps(entries,indent=2)+'\n')
    columns=['source_revision','source_sha256','candidate_season','author_date','id','code','official_player_code',
        'first_name','second_name','identity_status']
    bad.reindex(columns=columns).to_csv(out/'discrepancies.csv',index=False)
    report=dict(version='geek-season-context-v1',implementation_sha256=digest(Path(__file__).read_bytes()),
        parent_report_sha256=parent['report_sha256'],gt_dataset_id=GT_ID,gt_manifest_sha256=GT_MANIFEST,fixture_sha256=FIXTURES,
        snapshots=len(entries),candidate_snapshot_counts=dict(Counter(e['candidate_season'] for e in entries if e['candidate_season'])),
        identity_counts=dict(counts),candidate_seasons={s:dict(c) for s,c in per_season.items()},
        discrepancy_states=len(bad),discrepancy_pairs=bad[['candidate_season','id','code','official_player_code']].drop_duplicates().to_dict('records') if len(bad) else [],
        finalized_labels_admitted=0,training_admitted=False,gt_changed=False,production_changed=False,
        limitations=['roster_match_scoped_to_two_reference_seasons','not_independent_source_season_proof',
            'matching_id_and_code_not_publication_evidence','author_date_not_snapshot_availability',
            'source_code_conflicts_preserved_without_alias_or_repair'],
        artifacts={n:digest((out/n).read_bytes()) for n in ('snapshots.json','discrepancies.csv')})
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.base,a.out),indent=2))
