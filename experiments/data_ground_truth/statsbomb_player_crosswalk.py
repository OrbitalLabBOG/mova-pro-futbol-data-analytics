"""Conservative research identity linkage from club, fixture and repeated names."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from decimal import Decimal
import csv
import gzip
import io
import json
from pathlib import Path

from experiments.data_ground_truth.identity_2014 import name_tokens
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.statsbomb_open import read_record
from experiments.data_ground_truth.statsbomb_fixture_crosswalk import CLUBS
from experiments.data_ground_truth.training_dataset import checked, verify


def archive_code(value):
    if value in ('',None):return None
    number=Decimal(value)
    if not number.is_finite() or number<=0 or number!=number.to_integral_value():raise ValueError('invalid archive code')
    return str(int(number))


def compatible_names(left,right):
    a=name_tokens(left);b=name_tokens(right)
    return min(len(a),len(b))>=2 and (a<=b or b<=a)


def resolve(witnesses):
    candidates=defaultdict(lambda:defaultdict(set))
    for r in witnesses:candidates[r['statsbomb_player_id']][r['official_player_code']].add(r['fixture'])
    accepted={p:next(iter(codes)) for p,codes in candidates.items() if len(codes)==1 and len(next(iter(codes.values())))>=2}
    reverse=defaultdict(set)
    for player,codes in candidates.items():
        for code in codes:reverse[code].add(player)
    return {p:c for p,c in accepted.items() if len(reverse[c])==1}


def build(statsbomb_root,fixture_root,archive_root,package,out):
    link_bytes=(fixture_root/'report.json').read_bytes();link_report=json.loads(link_bytes)
    links=json.loads(checked(fixture_root/'fixture-links.json',link_report['artifacts']['fixture-links.json']))
    if len(links)!=380 or not all(r['research_link_accepted'] for r in links):raise ValueError('incomplete fixture reference')
    crosswalk_bytes=(archive_root/'crosswalk-report.json').read_bytes();crosswalk=json.loads(crosswalk_bytes)
    observations_bytes=checked(archive_root/'crosswalk/2015-16/player_match_observations.csv',crosswalk['seasons']['2015-16']['observation_sha256'])
    observations=list(csv.DictReader(io.StringIO(observations_bytes.decode())))
    candidates=defaultdict(list)
    for number,row in enumerate(observations,start=2):
        code=archive_code(row['official_player_code']);minutes=row['minutesPlayed']
        if code is not None and minutes and float(minutes)>0:
            candidates[(int(row['matchId_events']),int(row['team_id']))].append(dict(code=code,name=row['playerName'],csv_row=number))
    manifest_bytes=(statsbomb_root/'manifest.json').read_bytes();manifest=json.loads(manifest_bytes)
    records={r['path']:r for r in manifest['records']}
    club_map={c:a for a,b,c,d in CLUBS};roster={};names=defaultdict(set);witnesses=[];sources=[]
    for link in sorted(links,key=lambda r:r['archive_fixture']):
        record=records[f"data/lineups/{link['statsbomb_match_id']}.json"]
        teams=json.loads(read_record(statsbomb_root,record));sources.append(dict(path=record['path'],sha256=record['sha256']))
        for team in teams:
            club=club_map[team['team_id']]
            for player in team['lineup']:
                player_id=player['player_id'];fixture=link['archive_fixture'];key=(fixture,player_id)
                if key in roster:raise ValueError('duplicate lineup identity')
                names[player_id].add(player['player_name'])
                roster[key]=dict(positions_present=bool(player['positions']),source_sha256=record['sha256'])
                if not player['positions']:continue
                for candidate in candidates[(fixture,club)]:
                    if compatible_names(player['player_name'],candidate['name']):
                        witnesses.append(dict(statsbomb_player_id=player_id,official_player_code=candidate['code'],fixture=fixture,
                            club_code=club,statsbomb_name=player['player_name'],archive_name=candidate['name'],
                            archive_csv_row=candidate['csv_row'],lineup_sha256=record['sha256']))
    accepted=resolve(witnesses);reverse={c:p for p,c in accepted.items()};by_player=defaultdict(list)
    for row in witnesses:by_player[row['statsbomb_player_id']].append(row)
    player_links=[]
    for player in sorted(names):
        rows=by_player[player];codes={r['official_player_code'] for r in rows}
        status='accepted_research_identity' if player in accepted else 'no_name_witness' if not rows else 'ambiguous_or_insufficient_witnesses'
        player_links.append(dict(statsbomb_player_id=player,names=sorted(names[player]),official_player_code=accepted.get(player),
            status=status,candidate_codes=sorted(codes),witness_fixtures=len({r['fixture'] for r in rows}),training_admitted=False))
    dataset=verify(package)
    if dataset['dataset_id']!=link_report['dataset_id']:raise ValueError('different GT version')
    part=next(r for r in dataset['partitions'] if r['season']=='2015-16')
    labels=list(csv.DictReader(io.StringIO(gzip.decompress(checked(package/part['file'],part['sha256'])).decode())))
    counts=Counter();positive=Counter();issues=[];gt_codes=set()
    for row in labels:
        code=archive_code(row['official_player_code']);gt_codes.add(code);player=reverse.get(code);entry=roster.get((int(row['fixture']),player))
        status='unresolved_identity' if player is None else 'outside_match_lineup' if entry is None else 'lineup_present'
        counts[status]+=1
        if float(row['minutes'])>0:
            detail=status if status!='lineup_present' else 'positions_present' if entry['positions_present'] else 'positions_absent'
            positive[detail]+=1
            if detail!='positions_present':issues.append(dict(element=row['element'],fixture=row['fixture'],official_player_code=code,status=detail))
    out.mkdir(parents=True,exist_ok=True)
    (out/'player-links.json').write_text(json.dumps(player_links,indent=2)+'\n')
    (out/'witnesses.jsonl.gz').write_bytes(gzip.compress(('\n'.join(json.dumps(r,sort_keys=True) for r in witnesses)+'\n').encode(),mtime=0))
    (out/'positive-appearance-issues.json').write_text(json.dumps(issues,indent=2)+'\n')
    report=dict(version='statsbomb-player-crosswalk-v1',dataset_id=dataset['dataset_id'],fixture_report_sha256=digest(link_bytes),
        archive_crosswalk_report_sha256=digest(crosswalk_bytes),archive_observations_sha256=digest(observations_bytes),
        statsbomb_manifest_sha256=digest(manifest_bytes),implementation_sha256=digest(Path(__file__).read_bytes()),
        source_lineups=sources,statsbomb_players=len(names),identity_status=dict(Counter(r['status'] for r in player_links)),
        name_witnesses=len(witnesses),accepted_players=len(accepted),GT_unique_player_codes=len(gt_codes),
        GT_codes_resolved=len(gt_codes & set(reverse)),GT_rows=len(labels),GT_row_status=dict(counts),
        GT_positive_appearance_status=dict(positive),training_admitted=False,commercial_runtime_admitted=False,
        raw_redistribution_admitted=False,new_FPL_labels=0,production_changed=False,
        method='two_distinct_played_fixture_club_name_token_subset_witnesses_unique_reciprocal_code',
        limitations=['name_normalization_not_biographical_identity_verification',
            'position_interval_presence_not_exact_minutes_equivalence',
            'unresolved_and_single_appearance_players_not_forced',
            'research_only_StatsBomb_rights_and_temporal_limits_inherited'],
        artifacts={n:digest((out/n).read_bytes()) for n in ('player-links.json','witnesses.jsonl.gz','positive-appearance-issues.json')})
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('statsbomb-root','fixture-root','archive-root','package','out'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.statsbomb_root,a.fixture_root,a.archive_root,a.package,a.out),indent=2))


if __name__=='__main__':main()
