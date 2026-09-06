"""Pinned StatsBomb research-only archive; no commercial/runtime admission."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path

from experiments.data_ground_truth.raw import capture, digest
from experiments.data_ground_truth.training_dataset import checked

REPOSITORY = 'hudl/open-data'
REVISION = 'b0bc9f22dd77c206ddedc1d742893b3bbe64baec'
SEASONS = {'27':'2015/2016', '44':'2003/2004'}
BASE_PATHS = ['README.md','LICENSE.pdf','data/competitions.json'] + [f'data/matches/2/{season}.json' for season in SEASONS]


def read_record(root, record):
    if record['repository'] != REPOSITORY or record['revision'] != REVISION:
        raise ValueError('unexpected source binding')
    body = checked(root/'objects'/record['sha256'],record['sha256'])
    if len(body) != record['bytes']: raise ValueError('source size mismatch')
    return body


def match_ids(matches):
    ids = [row['match_id'] for row in matches]
    if any(type(i) is not int or i <= 0 for i in ids) or len(ids)!=len(set(ids)):
        raise ValueError('invalid or duplicate match ID')
    return ids


def acquire(root):
    records = [capture(root,REPOSITORY,REVISION,path) for path in BASE_PATHS]
    paths = []
    for record in records:
        if record['path'].startswith('data/matches/'):
            ids = match_ids(json.loads(read_record(root,record)))
            paths += [f'data/{table}/{match}.json' for match in ids for table in ('events','lineups')]
    if len(paths)!=len(set(paths)):raise ValueError('cross-season match collision')
    errors = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures={pool.submit(capture,root,REPOSITORY,REVISION,path):path for path in paths}
        for future in as_completed(futures):
            try: records.append(future.result())
            except Exception as exc: errors.append(dict(path=futures[future],error=str(exc)))
            if (len(records)+len(errors))%50 == 0: print(f'captured={len(records)} errors={len(errors)}',flush=True)
    manifest=dict(version='statsbomb-open-raw-v1',repository=REPOSITORY,revision=REVISION,
        expected_paths=BASE_PATHS+paths,records=sorted(records,key=lambda r:r['path']),errors=errors,
        usage='research_only',commercial_runtime_admitted=False,raw_redistribution_admitted=False)
    (root/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest


def fixture_coverage(matches):
    teams={row[side][side+'_id'] for row in matches for side in ('home_team','away_team')}
    pairs=[(r['home_team']['home_team_id'],r['away_team']['away_team_id']) for r in matches]
    expected={(a,b) for a in teams for b in teams if a!=b}
    return dict(teams=len(teams),matches=len(matches),unique_directed_pairs=len(set(pairs)),
        duplicate_pair_excess=len(pairs)-len(set(pairs)),missing_directed_pairs=len(expected-set(pairs)),
        complete_20_team_double_round_robin=len(teams)==20 and len(pairs)==380 and set(pairs)==expected)


def build(root,out):
    manifest_bytes=(root/'manifest.json').read_bytes();manifest=json.loads(manifest_bytes)
    paths=[r['path'] for r in manifest['records']]
    if manifest['errors'] or len(paths)!=len(set(paths)) or set(paths)!=set(manifest['expected_paths']):
        raise ValueError('incomplete or duplicate acquisition')
    records={r['path']:r for r in manifest['records']}
    for path in BASE_PATHS:read_record(root,records[path])
    seasons={};index=[];expected=set(BASE_PATHS);global_ids=set();global_duplicates=0
    for season,name in SEASONS.items():
        matches=json.loads(read_record(root,records[f'data/matches/2/{season}.json']))
        ids=match_ids(matches);types=Counter();status=Counter();total_events=0;total_lineup_players=0
        if any(r['competition']['competition_id']!=2 or str(r['season']['season_id'])!=season for r in matches):
            raise ValueError('competition or season mismatch')
        for match in sorted(matches,key=lambda r:r['match_id']):
            ident=match['match_id']; event_path=f'data/events/{ident}.json';lineup_path=f'data/lineups/{ident}.json'
            expected.update((event_path,lineup_path))
            events=json.loads(read_record(root,records[event_path]));lineups=json.loads(read_record(root,records[lineup_path]))
            event_ids=[e['id'] for e in events];duplicate_ids=len(event_ids)-len(set(event_ids))
            global_duplicates+=sum(e in global_ids for e in event_ids);global_ids.update(event_ids)
            roster={p['player_id'] for team in lineups for p in team['lineup']}
            observed={e['player']['id'] for e in events if 'player' in e}
            lineup_teams={t['team_id'] for t in lineups}
            match_teams={match['home_team']['home_team_id'],match['away_team']['away_team_id']}
            types.update(e['type']['name'] for e in events);status[match['match_status']]+=1
            total_events+=len(events);total_lineup_players+=sum(len(t['lineup']) for t in lineups)
            index.append(dict(season=name,match_id=ident,match_date=match['match_date'],events=len(events),
                lineup_players=sum(len(t['lineup']) for t in lineups),duplicate_event_ids=duplicate_ids,
                lineup_teams_match=lineup_teams==match_teams,unmapped_event_player_ids=sorted(observed-roster),
                event_sha256=records[event_path]['sha256'],lineup_sha256=records[lineup_path]['sha256'],
                available_at=None,eligible_predeadline=False,training_admitted=False))
        seasons[name]=dict(**fixture_coverage(matches),events=total_events,lineup_player_rows=total_lineup_players,
            match_status=dict(status),event_types=dict(sorted(types.items())),
            first_date=min(r['match_date'] for r in matches),last_date=max(r['match_date'] for r in matches))
    if set(records)!=expected:raise ValueError('unexpected files outside derived scope')
    out.mkdir(parents=True,exist_ok=True)
    (out/'match-index.json').write_text(json.dumps(index,indent=2)+'\n')
    result=dict(version='statsbomb-open-coverage-v1',raw_manifest_sha256=digest(manifest_bytes),
        implementation_sha256=digest(Path(__file__).read_bytes()),repository=REPOSITORY,revision=REVISION,
        source_files=len(records),source_bytes=sum(r['bytes'] for r in records.values()),seasons=seasons,
        global_duplicate_event_ids=global_duplicates,
        matches_with_duplicate_event_ids=sum(bool(r['duplicate_event_ids']) for r in index),
        matches_with_unmapped_event_players=sum(bool(r['unmapped_event_player_ids']) for r in index),
        mismatched_lineup_teams=sum(not r['lineup_teams_match'] for r in index),
        empty_event_files=sum(r['events']==0 for r in index),
        license_sha256=records['LICENSE.pdf']['sha256'],usage='research_only',
        commercial_runtime_admitted=False,raw_redistribution_admitted=False,training_admitted=False,
        new_FPL_labels=0,production_changed=False,
        limitations=['event_coverage_not_FPL_labels_or_identity_join',
            'full_fixture_schedule_not_proof_all_events_accurate',
            'license_restricts_commercial_use_and_raw_redistribution',
            'unknown_historical_publication_no_predeadline_admission'],
        artifacts={'match-index.json':digest((out/'match-index.json').read_bytes())})
    (out/'report.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);p.add_argument('--acquire',action='store_true');a=p.parse_args()
    if a.acquire:acquire(a.root)
    print(json.dumps(build(a.root,a.out),indent=2))


if __name__=='__main__':main()
