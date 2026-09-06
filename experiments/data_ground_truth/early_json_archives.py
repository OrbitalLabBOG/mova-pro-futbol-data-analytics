"""Normalize newly recovered partial FPL JSON archives without GT promotion."""
from __future__ import annotations
import argparse
import io
import json
from pathlib import Path

import pandas as pd

from experiments.data_ground_truth.historical_2014 import OPPONENT_CODES,reconcile_2014
from experiments.data_ground_truth.snapshots import unpack
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked,verify

SOURCES={
    'keithxm23/fplPlayer':(2013,'21c74e98562268738a7b520b0518e6a48068f0b3117dc0c2e33660016f4f515e'),
    'keithxm23/fplassistant':(2014,'4ba748103b6ba6abf3e8c1e8701cee3bb733f74e5570e2977f2b546670774e36'),
}


def normalize(players,fixtures,start):
    annual=[h[0] for p in players for h in p['season_history']]
    if max(annual)!=f'{start-1}/{str(start)[-2:]}':raise ValueError('annual history does not support declared season')
    weekly,metadata=unpack(players)
    if metadata.code.isna().any() or metadata.code.duplicated().any():raise ValueError('ambiguous declared player codes')
    codes=OPPONENT_CODES|dict(CAR=97,FUL=54,NOR=45) if start==2013 else OPPONENT_CODES
    has_history=metadata.id.isin(weekly.id)
    labels,report=reconcile_2014(weekly,metadata.loc[has_history],fixtures,season_start=start,opponent_codes=codes)
    labels=labels.merge(metadata[['id','code']],on='id',validate='many_to_one').rename(columns={'code':'official_player_code'})
    labels['eligible_training']=False
    metadata['declared_team_code']=[p['team_code'] for p in players]
    metadata['snapshot_team_name']=[p['team_name'] for p in players]
    metadata['available_at']=None;metadata['eligible_training']=False;metadata['eligible_predeadline']=False
    clubs=set(fixtures.home_team_id)|set(fixtures.away_team_id)
    report.update(snapshot_players=len(metadata),snapshot_players_without_history=int((~has_history).sum()),
        positive_point_metadata_without_history=int((~has_history & metadata.pts.gt(0)).sum()),
        snapshot_total_players_checked=int(has_history.sum()),positive_minute_rows=int(labels.mins.gt(0).sum()),explicit_zero_minute_rows=int(labels.mins.eq(0).sum()),
        declared_team_code_not_in_fixture_clubs=int((~metadata.declared_team_code.isin(clubs)).sum()),
        declared_team_code_equals_player_code=int(metadata.declared_team_code.eq(metadata.code).sum()),
        cross_season_identity_status='unique_source_declared_codes_not_yet_independently_validated',
        coverage_status='partial_snapshot_not_complete_season',points_total_scope='snapshot_total_not_final_season',
        training_admitted=False)
    return labels,metadata,report



def state_history(base):
    root=base/'early-fpl-state-history-g88';manifest_bytes=(root/'manifest.json').read_bytes()
    records=json.loads(manifest_bytes)['records'];revisions={};history_sources={}
    for name in ('keithxm23--fplassistant-history.json','keithxm23--fplassistant-dev-history.json'):
        raw=(base/'historical-discovery-g88'/name).read_bytes();history_sources[name]=digest(raw)
        for commit in json.loads(raw):revisions[commit['sha']]=commit['commit']['committer']['date']
    if {r['revision'] for r in records}!=set(revisions) or len(records)!=len(revisions):
        raise ValueError('historical revisions incomplete or duplicated')
    entries=[]
    for record in records:
        raw=checked(root/'objects'/record['sha256'],record['sha256'])
        if len(raw)!=record['bytes']:raise ValueError('historical snapshot size mismatch')
        weekly,metadata=unpack(json.loads(raw))
        entries.append(dict(revision=record['revision'],source_sha256=record['sha256'],bytes=len(raw),
            git_committer_time=revisions[record['revision']],players=len(metadata),history_rows=len(weekly),
            gameweeks=sorted(int(x) for x in weekly.gw.unique()) if len(weekly) else [],
            available_at=None,eligible_predeadline=False,eligible_training=False))
    summary=dict(manifest_sha256=digest(manifest_bytes),git_history_response_sha256=history_sources,
        snapshots=len(entries),bytes=sum(r['bytes'] for r in entries),unique_contents=len({r['source_sha256'] for r in entries}),
        snapshots_without_match_history=sum(r['history_rows']==0 for r in entries),
        earliest_git_committer_time=min(revisions.values()),latest_git_committer_time=max(revisions.values()),
        publication_proven=False)
    return summary,sorted(entries,key=lambda r:(r['git_committer_time'],r['revision']))


def build(base,out):
    root=base/'early-fpl-json-g88';raw_manifest=(root/'manifest.json').read_bytes();manifest=json.loads(raw_manifest)
    archive=base/'raw-history-v2';archive_bytes=(archive/'manifest.json').read_bytes();archive_manifest=json.loads(archive_bytes)
    pointer=json.loads(Path(__file__).with_name('current-labels.json').read_text());package=base/'training-datasets'/pointer['dataset_id']
    checked(package/'manifest.json',pointer['manifest_sha256']);gt=verify(package)
    report=dict(version='early-json-archives-v1',source_manifest_sha256=digest(raw_manifest),fixture_manifest_sha256=digest(archive_bytes),
                gt_dataset_id=gt['dataset_id'],implementation_sha256=digest(Path(__file__).read_bytes()),seasons={},artifacts={})
    out.mkdir(parents=True,exist_ok=True)
    for repo,(start,expected) in SOURCES.items():
        record=next(r for r in manifest['records'] if r['repository']==repo and r['path']=='data.json')
        if record['sha256']!=expected:raise ValueError('unexpected historical source')
        players=json.loads(checked(root/'objects'/expected,expected));season=f'{start}-{str(start+1)[-2:]}'
        records=[r for r in archive_manifest['records'] if r['repository'].startswith('imadeddine-belkat/') and r['path']==f'pl_stats/_merged/events/{season}_events_stats.csv']
        if len(records)!=1:raise ValueError('fixture source ambiguity')
        fixture=records[0];fixtures=pd.read_csv(io.BytesIO(checked(archive/'objects'/fixture['sha256'],fixture['sha256'])))
        labels,metadata,quality=normalize(players,fixtures,start)
        labels['source_sha256']=expected;metadata['source_sha256']=expected
        quality.update(repository=repo,source_sha256=expected,fixture_sha256=fixture['sha256'])
        if start==2014:
            partition=next(e for e in gt['partitions'] if e['season']==season)
            existing=pd.read_csv(package/partition['file'],compression='gzip')
            paired=labels.merge(existing,left_on=['id','matchId'],right_on=['element','fixture'],how='left',validate='one_to_one',indicator=True,suffixes=('_archive','_gt'))
            comparable=paired['_merge'].eq('both')
            quality['GT_comparison']=dict(rows=len(paired),missing_in_GT=int((~comparable).sum()),
                minutes_disagreements=int((comparable&paired.mins.ne(paired.minutes)).sum()),
                points_disagreements=int((comparable&paired.gw_pts.ne(paired.total_points)).sum()),
                gameweek_disagreements=int((comparable&paired.gw_archive.ne(paired.gw_gt)).sum()),
                comparable_official_code_rows=int((comparable&paired.official_player_code_gt.notna()).sum()),
                official_code_disagreements=int((comparable&paired.official_player_code_gt.notna()&paired.official_player_code_archive.ne(paired.official_player_code_gt)).sum()))
        for suffix,frame in [('labels',labels),('metadata',metadata)]:
            name=f'{season}-{suffix}.csv';frame.to_csv(out/name,index=False);report['artifacts'][name]=digest((out/name).read_bytes())
        report['seasons'][season]=quality
    history,entries=state_history(base)
    history_name='historical_state_snapshots.json'
    (out/history_name).write_text(json.dumps(entries,indent=2)+'\n')
    report['artifacts'][history_name]=digest((out/history_name).read_bytes())
    report['historical_state_source']=history
    report.update(new_complete_seasons=0,training_admitted=False,production_changed=False,
        limitations=['new_source_rows_not_claimed_unique_vs_all_existing_partial_archives',
                     'snapshot_point_totals_not_full_season_coverage','raw_team_code_not_used_to_bind_fixtures',
                     'dates_reconciled_as_local_wall_clock_not_publication_time',
                     'annual_histories_preserved_in_raw_not_misrepresented_as_match_labels'])
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.base,a.out),indent=2))
