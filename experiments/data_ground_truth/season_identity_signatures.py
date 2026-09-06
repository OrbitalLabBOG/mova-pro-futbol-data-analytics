"""Research identity evidence from exact, complete season appearance signatures."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import gzip
import io
import json
from pathlib import Path
import unicodedata
import re

from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.statsbomb_open import read_record
from experiments.data_ground_truth.statsbomb_fixture_crosswalk import CLUBS
from experiments.data_ground_truth.statsbomb_player_crosswalk import archive_code
from experiments.data_ground_truth.training_dataset import checked, verify


def signature_candidates(provider, archive, FPL_fixtures):
    """Uniqueness is evaluated across all profiles, before names or baseline filtering."""
    left = defaultdict(list); right = defaultdict(list); eligibility = Counter(); complete = set()
    for player, values in provider.items():
        signature = frozenset(values)
        if len({fixture for fixture, club in signature}) >= 2:
            left[signature].append(player)
    for code, values in archive.items():
        signature = frozenset(values)
        if len({fixture for fixture, club in signature}) < 2:
            eligibility['fewer_than_two_fixtures'] += 1
            continue
        right[signature].append(code)
        if {fixture for fixture, club in signature} != FPL_fixtures.get(code, set()):
            eligibility['different_or_missing_FPL_fixture_set'] += 1
        else:
            eligibility['eligible'] += 1; complete.add(code)
    output = []
    for signature in sorted(set(left) & set(right), key=lambda s: sorted(s)):
        players = sorted(left[signature]); codes = sorted(right[signature])
        output.append(dict(fixtures=sorted(signature), statsbomb_player_ids=players,
                           archive_profile_keys=codes,
                           status=('ambiguous_signature' if len(players)!=1 or len(codes)!=1 else
                                   'unique_signature' if codes[0] in complete else 'incomplete_FPL_signature')))
    return output, dict(eligibility)


def supporting_name(left, right):
    def words(name):
        value=unicodedata.normalize('NFKD',name).encode('ascii','ignore').decode().lower()
        return re.findall('[a-z]+',value)
    a=words(left); b=words(right)
    return (len(a)>=2 and len(b)>=2 and len(a[-1])>=3 and a[-1]==b[-1] and a[0][0]==b[0][0])


def build(root, archive_root, fixture_root, baseline_root, package, out):
    baseline_bytes=(baseline_root/'report.json').read_bytes(); baseline=json.loads(baseline_bytes)
    dataset=verify(package)
    if dataset['dataset_id']!=baseline['dataset_id']:raise ValueError('different GT baseline')
    part=next(p for p in dataset['partitions'] if p['season']=='2015-16')
    labels=list(csv.DictReader(io.StringIO(gzip.decompress(checked(package/part['file'],part['sha256'])).decode())))
    FPL_fixtures=defaultdict(set)
    for row in labels:
        if float(row['minutes'])>0:FPL_fixtures[archive_code(row['official_player_code'])].add(int(row['fixture']))
    fixture_bytes=(fixture_root/'report.json').read_bytes()
    if digest(fixture_bytes)!=baseline['fixture_report_sha256']:raise ValueError('different fixture baseline')
    fixture_report=json.loads(fixture_bytes)
    links=json.loads(checked(fixture_root/'fixture-links.json',fixture_report['artifacts']['fixture-links.json']))
    if len(links)!=380 or len({r['archive_fixture'] for r in links})!=380:raise ValueError('incomplete season fixtures')
    manifest_bytes=(root/'manifest.json').read_bytes()
    if digest(manifest_bytes)!=baseline['statsbomb_manifest_sha256']:raise ValueError('different provider baseline')
    records={r['path']:r for r in json.loads(manifest_bytes)['records']}
    provider=defaultdict(set); provider_names=defaultdict(set); roster={}; source_lineups=[]
    club_map={c:a for a,_,c,_ in CLUBS}
    for link in links:
        record=records[f"data/lineups/{link['statsbomb_match_id']}.json"]
        source_lineups.append(dict(path=record['path'],sha256=record['sha256']))
        for team in json.loads(read_record(root,record)):
            club=club_map[team['team_id']]
            for player in team['lineup']:
                ident=player['player_id']; fixture=link['archive_fixture']; key=(fixture,ident)
                if key in roster:raise ValueError('duplicate lineup identity')
                roster[key]=dict(positions_present=bool(player['positions']),source_sha256=record['sha256'])
                provider_names[ident].add(player['player_name'])
                if player['positions']:provider[ident].add((fixture,club))
    observation_bytes=checked(archive_root/'crosswalk/2015-16/player_match_observations.csv',baseline['archive_observations_sha256'])
    archive=defaultdict(set); archive_names=defaultdict(set); archive_rows={}
    for number,row in enumerate(csv.DictReader(io.StringIO(observation_bytes.decode())),start=2):
        code=archive_code(row['official_player_code'])
        if not row['minutesPlayed'] or float(row['minutesPlayed'])<=0:continue
        if code is None:
            source_id=archive_code(row['playerId'])
            if source_id is None:raise ValueError('anonymous archive profile lacks source ID')
            code='missing_code:'+source_id
        fixture=int(row['matchId_events']); club=int(row['team_id']); key=(code,fixture,club)
        if key in archive_rows:raise ValueError('duplicate positive archive identity')
        archive_rows[key]=dict(csv_row=number,name=row['playerName'])
        archive[code].add((fixture,club)); archive_names[code].add(row['playerName'])
    candidates,eligibility=signature_candidates(provider,archive,FPL_fixtures)
    player_links=json.loads(checked(baseline_root/'player-links.json',baseline['artifacts']['player-links.json']))
    if {r['statsbomb_player_id'] for r in player_links}!=set(provider_names):raise ValueError('baseline player universe differs')
    old={r['statsbomb_player_id']:r['official_player_code'] for r in player_links if r['status']=='accepted_research_identity'}
    if len(old)!=baseline['accepted_players'] or len(set(old.values()))!=len(old):raise ValueError('invalid baseline identities')
    occupied={code:player for player,code in old.items()}; additions={}; conflicts=[]
    for candidate in candidates:
        if candidate['status']!='unique_signature':continue
        player=candidate['statsbomb_player_ids'][0]; code=candidate['archive_profile_keys'][0]
        candidate['provider_names']=sorted(provider_names[player]); candidate['archive_names']=sorted(archive_names[code])
        if not any(supporting_name(a,b) for a in provider_names[player] for b in archive_names[code]):
            candidate['status']='name_guard_failed';continue
        if (player in old and old[player]!=code) or (code in occupied and occupied[code]!=player):
            candidate['status']='baseline_conflict';conflicts.append(candidate);continue
        candidate['status']='agrees_with_baseline' if player in old else 'new_research_identity'
        if player not in old:additions[player]=code
    if conflicts:raise ValueError('signature contradicts an existing identity; no extension emitted')
    accepted=old|additions
    for row in player_links:
        player=row['statsbomb_player_id']
        if player in additions:
            row.update(official_player_code=additions[player],status='accepted_research_identity',
                       candidate_codes=[additions[player]],witness_fixtures=len(provider[player]),
                       evidence_method='unique_complete_season_fixture_club_signature_with_name_guard')
    previous_witnesses=checked(baseline_root/'witnesses.jsonl.gz',baseline['artifacts']['witnesses.jsonl.gz'])
    witnesses=[json.loads(line) for line in gzip.decompress(previous_witnesses).decode().splitlines()]
    new_witnesses=[]
    for player,code in sorted(additions.items()):
        for fixture,club in sorted(provider[player]):
            ref=archive_rows[(code,fixture,club)]
            new_witnesses.append(dict(statsbomb_player_id=player,official_player_code=code,fixture=fixture,club_code=club,
                statsbomb_name=sorted(provider_names[player])[0],archive_name=ref['name'],archive_csv_row=ref['csv_row'],
                lineup_sha256=roster[(fixture,player)]['source_sha256'],name_evidence='complete_season_signature_with_name_guard'))
    witnesses.extend(new_witnesses)
    reverse={code:player for player,code in accepted.items()}; counts=Counter(); positive=Counter(); issues=[]
    for row in labels:
        code=archive_code(row['official_player_code']); player=reverse.get(code); entry=roster.get((int(row['fixture']),player))
        status='unresolved_identity' if player is None else 'outside_match_lineup' if entry is None else 'lineup_present'
        counts[status]+=1
        if float(row['minutes'])>0:
            detail=status if status!='lineup_present' else 'positions_present' if entry['positions_present'] else 'positions_absent'
            positive[detail]+=1
            if detail!='positions_present':issues.append(dict(element=row['element'],fixture=row['fixture'],official_player_code=code,status=detail))
    delta=[dict(statsbomb_player_id=p,before=old.get(p),after=c,status='retained' if p in old else 'new') for p,c in sorted(accepted.items())]
    out.mkdir(parents=True,exist_ok=True)
    for name,value in [('player-links.json',player_links),('signature-candidates.json',candidates),('positive-appearance-issues.json',issues),('identity-delta.json',delta)]:
        (out/name).write_text(json.dumps(value,indent=2)+'\n')
    (out/'witnesses.jsonl.gz').write_bytes(gzip.compress(('\n'.join(json.dumps(r,sort_keys=True) for r in witnesses)+'\n').encode(),mtime=0))
    report=dict(version='season-identity-signatures-v1',dataset_id=dataset['dataset_id'],partition_sha256=part['sha256'],
        baseline_report_sha256=digest(baseline_bytes),fixture_report_sha256=digest(fixture_bytes),statsbomb_manifest_sha256=digest(manifest_bytes),
        archive_observations_sha256=digest(observation_bytes),implementation_sha256=digest(Path(__file__).read_bytes()),source_lineups=source_lineups,
        accepted_players=len(accepted),statsbomb_players=len(player_links),GT_rows=len(labels),GT_row_status=dict(counts),
        GT_positive_appearance_status=dict(positive),baseline_positive_covered=baseline['GT_positive_appearance_status']['positions_present'],
        additional_positive_covered=positive['positions_present']-baseline['GT_positive_appearance_status']['positions_present'],
        identity_delta=dict(Counter(r['status'] for r in delta)),signature_status=dict(Counter(r['status'] for r in candidates)),
        archive_profile_eligibility=eligibility,new_signature_witnesses=len(new_witnesses),
        training_admitted=False,commercial_runtime_admitted=False,raw_redistribution_admitted=False,new_FPL_labels=0,production_changed=False,
        limitations=['exact_signature_uses_entire_retrospective_season_not_predeadline_information',
            'baseline_agreement_is_consistency_check_not_independent_accuracy_estimate',
            'name_guard_only_supports_signature_not_general_nickname_equivalence',
            'missing_archive_codes_and_incomplete_FPL_profiles_compete_for_uniqueness_but_cannot_be_admitted',
            'single_appearance_players_and_shared_signatures_not_forced',
            'research_only_StatsBomb_rights_and_temporal_limits_inherited'],
        artifacts={name:digest((out/name).read_bytes()) for name in ('player-links.json','signature-candidates.json','positive-appearance-issues.json','identity-delta.json','witnesses.jsonl.gz')})
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('root','archive-root','fixture-root','baseline-root','package','out'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.root,a.archive_root,a.fixture_root,a.baseline_root,a.package,a.out),indent=2))


if __name__=='__main__':main()
