"""Research comparison of event-derived goals/own goals with FPL labels."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import gzip
import io
import json
from pathlib import Path

from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.statsbomb_open import read_record
from experiments.data_ground_truth.statsbomb_player_crosswalk import archive_code
from experiments.data_ground_truth.training_dataset import checked, verify


def tally(events,teams):
    goals=Counter();own_goals=Counter();team_goals=Counter();witnesses=[];unknown_players=0
    for event in events:
        if event['period'] not in (1,2):continue
        kind=event['type']['name']
        is_goal=kind=='Shot' and event['shot']['outcome']['name']=='Goal'
        is_own=kind=='Own Goal Against'
        if not (is_goal or is_own):continue
        team=event['team']['id']
        if team not in teams or len(teams)!=2:raise ValueError('goal outside fixture teams')
        player=event.get('player',{}).get('id')
        if player is None:unknown_players+=1
        elif is_goal:goals[player]+=1
        else:own_goals[player]+=1
        credited=next(t for t in teams if t!=team) if is_own else team
        team_goals[credited]+=1
        witnesses.append(dict(event_id=event['id'],player_id=player,team_id=team,
            credited_team_id=credited,component='own_goals' if is_own else 'goals_scored'))
    return goals,own_goals,team_goals,witnesses,unknown_players


def compare(value,reference):
    if reference in ('',None):return dict(status='FPL_unknown',provider=value,FPL=None)
    number=float(reference)
    if not number.is_integer() or number<0:raise ValueError('invalid FPL component')
    return dict(status='equal' if value==number else 'different',provider=value,FPL=int(number),delta=value-int(number))


def build(root,identity_root,fixture_root,package,spec_root,out):
    identity_bytes=(identity_root/'report.json').read_bytes();identity=json.loads(identity_bytes)
    players=json.loads(checked(identity_root/'player-links.json',identity['artifacts']['player-links.json']))
    mapping={r['official_player_code']:r['statsbomb_player_id'] for r in players if r['status']=='accepted_research_identity'}
    if len(mapping)!=identity['accepted_players'] or len(set(mapping.values()))!=len(mapping):raise ValueError('ambiguous identity mapping')
    fixture_bytes=(fixture_root/'report.json').read_bytes();fixture_report=json.loads(fixture_bytes)
    if digest(fixture_bytes)!=identity['fixture_report_sha256']:raise ValueError('different fixture context')
    links=json.loads(checked(fixture_root/'fixture-links.json',fixture_report['artifacts']['fixture-links.json']))
    manifest_bytes=(root/'manifest.json').read_bytes();manifest=json.loads(manifest_bytes)
    if digest(manifest_bytes)!=identity['statsbomb_manifest_sha256']:raise ValueError('different StatsBomb context')
    records={r['path']:r for r in manifest['records']};calendar=json.loads(read_record(root,records['data/matches/2/27.json']))
    matches={r['match_id']:r for r in calendar};data={};match_checks=[];source_hashes=[];all_witnesses=[];unknown_actors=0
    for link in sorted(links,key=lambda r:r['archive_fixture']):
        match=matches[link['statsbomb_match_id']];ident=match['match_id']
        record=records[f'data/events/{ident}.json'];events=json.loads(read_record(root,record))
        if len(events)!=len({e['id'] for e in events}):raise ValueError('duplicate event ID')
        lineup_record=records[f'data/lineups/{ident}.json'];lineups=json.loads(read_record(root,lineup_record))
        roster={p['player_id'] for team in lineups for p in team['lineup']}
        home=match['home_team']['home_team_id'];away=match['away_team']['away_team_id']
        goals,own,team_goals,witnesses,unknown=tally(events,{home,away});unknown_actors+=unknown
        if unknown:raise ValueError('goal event without identified actor')
        data[link['archive_fixture']]=dict(roster=roster,goals_scored=goals,own_goals=own,source_sha256=record['sha256'])
        source_hashes.append(dict(match_id=ident,event_sha256=record['sha256'],lineup_sha256=lineup_record['sha256']))
        all_witnesses.extend(dict(**w,fixture=link['archive_fixture'],source_sha256=record['sha256']) for w in witnesses)
        for team,score in [(home,match['home_score']),(away,match['away_score'])]:
            match_checks.append(dict(match_id=ident,team_id=team,events_goals=team_goals[team],calendar_goals=score,
                status='equal' if team_goals[team]==score else 'different'))
    dataset=verify(package)
    if dataset['dataset_id']!=identity['dataset_id']:raise ValueError('different GT')
    part=next(r for r in dataset['partitions'] if r['season']=='2015-16')
    rows=list(csv.DictReader(io.StringIO(gzip.decompress(checked(package/part['file'],part['sha256'])).decode())))
    counts={metric:Counter() for metric in ('goals_scored','own_goals')};positive={k:Counter() for k in counts};nonzero={k:Counter() for k in counts};totals={k:Counter() for k in counts};coverage=Counter();output=[]
    for row in rows:
        code=archive_code(row['official_player_code']);player=mapping.get(code);fixture=int(row['fixture']);source=data.get(fixture)
        if source is None:coverage['no_fixture']+=1;continue
        if player is None:coverage['unresolved_identity']+=1;continue
        if player not in source['roster']:coverage['outside_lineup']+=1;continue
        coverage['compared']+=1;metrics={}
        for metric in counts:
            result=compare(source[metric][player],row[metric]);counts[metric][result['status']]+=1
            if float(row['minutes'])>0:positive[metric][result['status']]+=1
            if result['provider']>0 or (result['FPL'] is not None and result['FPL']>0):nonzero[metric][result['status']]+=1
            totals[metric]['provider']+=result['provider']
            if result['FPL'] is not None:totals[metric]['FPL']+=result['FPL']
            metrics[metric]=result
        output.append(dict(fixture=fixture,official_player_code=code,statsbomb_player_id=player,
            FPL_minutes=row['minutes'],metrics=metrics,event_source_sha256=source['source_sha256']))
    specs_bytes=(spec_root/'manifest.json').read_bytes();specs=json.loads(specs_bytes)
    if specs['errors']:raise ValueError('spec acquisition errors')
    for r in specs['records']:read_record(spec_root,r)
    out.mkdir(parents=True,exist_ok=True)
    (out/'comparisons.jsonl.gz').write_bytes(gzip.compress(('\n'.join(json.dumps(r,sort_keys=True) for r in output)+'\n').encode(),mtime=0))
    (out/'score-checks.json').write_text(json.dumps(match_checks,indent=2)+'\n')
    (out/'goal-witnesses.json').write_text(json.dumps(all_witnesses,indent=2)+'\n')
    report=dict(version='statsbomb-goal-calibration-v1',dataset_id=dataset['dataset_id'],identity_report_sha256=digest(identity_bytes),
        fixture_report_sha256=digest(fixture_bytes),statsbomb_manifest_sha256=digest(manifest_bytes),spec_manifest_sha256=digest(specs_bytes),
        implementation_sha256=digest(Path(__file__).read_bytes()),source_matches=source_hashes,coverage=dict(coverage),
        components={k:dict(v) for k,v in counts.items()},positive_components={k:dict(v) for k,v in positive.items()},
        nonzero_components={k:dict(v) for k,v in nonzero.items()},compared_component_totals={k:dict(v) for k,v in totals.items()},
        internal_score_status=dict(Counter(r['status'] for r in match_checks)),unknown_goal_actors=unknown_actors,
        counted_goal_events=len(all_witnesses),event_components=dict(Counter(r['component'] for r in all_witnesses)),
        training_admitted=False,commercial_runtime_admitted=False,raw_redistribution_admitted=False,new_FPL_labels=0,production_changed=False,
        limitations=['zero_is_derived_event_tally_with_lineup_presence_not_raw_missing_value_imputation',
            'unresolved_or_outside_lineup_rows_not_compared_as_zero',
            'internal_score_check_not_independent_outcome_validation',
            'Own_Goal_For_and_goalkeeper_conceded_events_not_counted_again',
            'research_only_StatsBomb_rights_and_temporal_limits_inherited'],
        artifacts={n:digest((out/n).read_bytes()) for n in ('comparisons.jsonl.gz','score-checks.json','goal-witnesses.json')})
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('root','identity-root','fixture-root','package','spec-root','out'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.root,a.identity_root,a.fixture_root,a.package,a.spec_root,a.out),indent=2))


if __name__=='__main__':main()
