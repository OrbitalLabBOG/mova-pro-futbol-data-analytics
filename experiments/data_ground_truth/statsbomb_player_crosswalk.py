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


def name_evidence(player, archive_name, declared_aliases=False):
    if compatible_names(player['player_name'], archive_name): return 'full_name'
    alias = player.get('player_nickname')
    if declared_aliases and alias and name_tokens(alias) and name_tokens(alias)==name_tokens(archive_name):
        return 'declared_alias'
    return None


def candidate_name_evidence(player, candidate, declared_aliases, metadata_by_code):
    evidence = name_evidence(player, candidate['name'], declared_aliases)
    metadata = metadata_by_code.get(candidate['code'])
    if evidence is None and metadata is not None:
        extra = name_evidence(player, metadata['full_name'], True)
        if extra is not None: evidence = 'fpl_metadata_' + extra
    return evidence, metadata


def recover_archive_codes(observations, metadata_by_code, labels):
    """Propose absent PL codes from unique FPL names and same-fixture appearances."""
    positive = {(int(r['fixture']), archive_code(r['official_player_code']))
                for r in labels if r['minutes'] and float(r['minutes']) > 0}
    existing = {(int(r['matchId_events']), archive_code(r['official_player_code']))
                for r in observations if archive_code(r['official_player_code']) is not None}
    proposals = []; output = []
    for number, row in enumerate(observations, start=2):
        if archive_code(row['official_player_code']) is not None or not row['minutesPlayed'] or float(row['minutesPlayed']) <= 0:
            continue
        fixture = int(row['matchId_events'])
        candidates = [code for code, meta in metadata_by_code.items()
                      if compatible_names(row['playerName'], meta['full_name'])]
        code = candidates[0] if len(candidates) == 1 else None
        status = ('no_unique_full_name' if code is None else
                  'no_FPL_positive_appearance' if (fixture, code) not in positive else
                  'code_already_present_in_fixture' if (fixture, code) in existing else 'candidate')
        item = dict(archive_csv_row=number, fixture=fixture, club_code=int(row['team_id']),
                    archive_name=row['playerName'], candidate_codes=sorted(candidates), status=status,
                    official_player_code=code)
        if code is not None:
            item['fpl_name_source'] = metadata_by_code[code]
        output.append(item)
        if status == 'candidate': proposals.append(item)
    counts = Counter((r['fixture'], r['official_player_code']) for r in proposals)
    recovered = {}
    for item in proposals:
        if counts[(item['fixture'], item['official_player_code'])] != 1:
            item['status'] = 'competing_missing_rows'
        else:
            item['status'] = 'proposed_code_only'
            recovered[item['archive_csv_row']] = item
    return recovered, output


def build(statsbomb_root,fixture_root,archive_root,package,out,declared_aliases=False,baseline_root=None,fpl_names_root=None,recover_missing_codes=False):
    if declared_aliases and baseline_root is None: raise ValueError('alias comparison requires baseline')
    if fpl_names_root is not None and not declared_aliases: raise ValueError('FPL names require explicit alias mode')
    if recover_missing_codes and fpl_names_root is None: raise ValueError('code recovery requires FPL metadata and baseline')
    fpl_names={};name_manifest_bytes=None
    if fpl_names_root is not None:
        name_manifest_bytes=(fpl_names_root/'manifest.json').read_bytes();name_manifest=json.loads(name_manifest_bytes)
        if name_manifest['errors']:raise ValueError('FPL name acquisition errors')
        for record in name_manifest['records']:
            if not record['path'].startswith('PlayersInfo/') or not record['path'].endswith('.json'):continue
            if record['repository']!='mvbfontes/premierleaguedatasets':raise ValueError('unexpected FPL name source')
            player=json.loads(checked(fpl_names_root/'objects'/record['sha256'],record['sha256']))
            code=archive_code(str(player['code']));full_name=player['first_name']+' '+player['second_name']
            if code in fpl_names:raise ValueError('duplicate FPL name code')
            fpl_names[code]=dict(full_name=full_name,source_sha256=record['sha256'],path=record['path'])
    link_bytes=(fixture_root/'report.json').read_bytes();link_report=json.loads(link_bytes)
    links=json.loads(checked(fixture_root/'fixture-links.json',link_report['artifacts']['fixture-links.json']))
    if len(links)!=380 or not all(r['research_link_accepted'] for r in links):raise ValueError('incomplete fixture reference')
    crosswalk_bytes=(archive_root/'crosswalk-report.json').read_bytes();crosswalk=json.loads(crosswalk_bytes)
    observations_bytes=checked(archive_root/'crosswalk/2015-16/player_match_observations.csv',crosswalk['seasons']['2015-16']['observation_sha256'])
    observations=list(csv.DictReader(io.StringIO(observations_bytes.decode())))
    recovered={};recovery_audit=[]
    if recover_missing_codes:
        recovery_dataset=verify(package)
        recovery_part=next(r for r in recovery_dataset['partitions'] if r['season']=='2015-16')
        recovery_labels=list(csv.DictReader(io.StringIO(gzip.decompress(checked(package/recovery_part['file'],recovery_part['sha256'])).decode())))
        recovered,recovery_audit=recover_archive_codes(observations,fpl_names,recovery_labels)
    candidates=defaultdict(list)
    for number,row in enumerate(observations,start=2):
        code=archive_code(row['official_player_code']);minutes=row['minutesPlayed']
        if code is None and number in recovered: code=recovered[number]['official_player_code']
        if code is not None and minutes and float(minutes)>0:
            candidates[(int(row['matchId_events']),int(row['team_id']))].append(dict(code=code,name=row['playerName'],csv_row=number))
    manifest_bytes=(statsbomb_root/'manifest.json').read_bytes();manifest=json.loads(manifest_bytes)
    records={r['path']:r for r in manifest['records']}
    club_map={c:a for a,b,c,d in CLUBS};roster={};names=defaultdict(set);witnesses=[];sources=[];aliases=defaultdict(set)
    for link in sorted(links,key=lambda r:r['archive_fixture']):
        record=records[f"data/lineups/{link['statsbomb_match_id']}.json"]
        teams=json.loads(read_record(statsbomb_root,record));sources.append(dict(path=record['path'],sha256=record['sha256']))
        for team in teams:
            club=club_map[team['team_id']]
            for player in team['lineup']:
                player_id=player['player_id'];fixture=link['archive_fixture'];key=(fixture,player_id)
                if key in roster:raise ValueError('duplicate lineup identity')
                names[player_id].add(player['player_name'])
                if player.get('player_nickname'): aliases[player_id].add(player['player_nickname'])
                roster[key]=dict(positions_present=bool(player['positions']),source_sha256=record['sha256'])
                if not player['positions']:continue
                for candidate in candidates[(fixture,club)]:
                    evidence, metadata = candidate_name_evidence(player,candidate,declared_aliases,fpl_names)
                    if evidence:
                        witnesses.append(dict(statsbomb_player_id=player_id,official_player_code=candidate['code'],fixture=fixture,
                            club_code=club,statsbomb_name=player['player_name'],archive_name=candidate['name'],
                            archive_csv_row=candidate['csv_row'],lineup_sha256=record['sha256']))
                        if declared_aliases: witnesses[-1].update(name_evidence=evidence,declared_alias=player.get('player_nickname'))
                        if evidence.startswith('fpl_metadata_'): witnesses[-1]['fpl_name_source']=metadata
                        if candidate['csv_row'] in recovered: witnesses[-1]['missing_code_recovery']=recovered[candidate['csv_row']]
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
    report=dict(version='statsbomb-player-crosswalk-v3' if fpl_names_root is not None else 'statsbomb-player-crosswalk-v2' if declared_aliases else 'statsbomb-player-crosswalk-v1',dataset_id=dataset['dataset_id'],fixture_report_sha256=digest(link_bytes),
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
    if declared_aliases:
        baseline_bytes=(baseline_root/'report.json').read_bytes();baseline=json.loads(baseline_bytes)
        if (baseline['dataset_id']!=dataset['dataset_id'] or baseline['fixture_report_sha256']!=digest(link_bytes)
                or baseline['archive_observations_sha256']!=digest(observations_bytes)
                or baseline['statsbomb_manifest_sha256']!=digest(manifest_bytes)):
            raise ValueError('different identity baseline context')
        if recover_missing_codes and baseline.get('fpl_names_manifest_sha256')!=digest(name_manifest_bytes):
            raise ValueError('different FPL metadata baseline context')
        previous=json.loads(checked(baseline_root/'player-links.json',baseline['artifacts']['player-links.json']))
        old={r['statsbomb_player_id']:r['official_player_code'] for r in previous if r['status']=='accepted_research_identity'}
        delta=[]
        for player in sorted(set(old)|set(accepted)):
            before=old.get(player);after=accepted.get(player)
            status='retained' if before==after else 'new' if before is None else 'lost' if after is None else 'changed'
            delta.append(dict(statsbomb_player_id=player,before=before,after=after,status=status))
        (out/'identity-delta.json').write_text(json.dumps(delta,indent=2)+'\n')
        report.update(baseline_report_sha256=digest(baseline_bytes),declared_alias_player_count=len(aliases),
            witness_name_evidence=dict(Counter(r['name_evidence'] for r in witnesses)),
            identity_delta=dict(Counter(r['status'] for r in delta)),
            baseline_positive_covered=baseline['GT_positive_appearance_status'].get('positions_present',0),
            additional_positive_covered=positive['positions_present']-baseline['GT_positive_appearance_status'].get('positions_present',0),
            method='full_name_or_exact_declared_alias_two_distinct_played_fixture_club_witnesses_unique_reciprocal_code')
        report['artifacts']['identity-delta.json']=digest((out/'identity-delta.json').read_bytes())
        report['limitations'].append('single_token_alias_only_when_explicitly_declared_by_provider_not_inferred')
    if fpl_names_root is not None:
        report.update(fpl_names_manifest_sha256=digest(name_manifest_bytes),fpl_name_records=len(fpl_names),
            method='PL_name_or_code_bound_FPL_full_name_or_explicit_SB_alias_two_fixture_club_witnesses_unique_reciprocal_code')
        report['limitations'].append('FPL_current_full_name_metadata_not_historical_availability_or_biographical_proof')
    if recover_missing_codes:
        (out/'missing-code-proposals.json').write_text(json.dumps(recovery_audit,indent=2)+'\n')
        report.update(version='statsbomb-player-crosswalk-v4',
            missing_code_status=dict(Counter(r['status'] for r in recovery_audit)),
            recovered_code_witnesses=sum('missing_code_recovery' in r for r in witnesses),
            method='G71_plus_unique_FPL_full_name_same_fixture_positive_appearance_for_absent_PL_codes_then_unchanged_two_fixture_reciprocal_resolution')
        report['artifacts']['missing-code-proposals.json']=digest((out/'missing-code-proposals.json').read_bytes())
        report['limitations'].append('missing_code_proposals_are_identity_evidence_not_raw_repairs_or_new_labels')
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('statsbomb-root','fixture-root','archive-root','package','out'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--declared-aliases',action='store_true');p.add_argument('--baseline-root',type=Path);p.add_argument('--fpl-names-root',type=Path)
    p.add_argument('--recover-missing-codes',action='store_true')
    a=p.parse_args();print(json.dumps(build(a.statsbomb_root,a.fixture_root,a.archive_root,a.package,a.out,a.declared_aliases,a.baseline_root,a.fpl_names_root,a.recover_missing_codes),indent=2))


if __name__=='__main__':main()
