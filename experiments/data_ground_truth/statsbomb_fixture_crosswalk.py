"""Research-only fixture linkage across explicit club namespaces."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime
import gzip
import io
import json
from pathlib import Path

from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.statsbomb_open import read_record
from experiments.data_ground_truth.training_dataset import checked, verify

# Explicit observed source IDs and labels; no numeric-ID equality assumption.
CLUBS = [(1,'Man Utd',39,'Manchester United'),(11,'Everton',29,'Everton'),
 (110,'Stoke',30,'Stoke City'),(13,'Leicester',22,'Leicester City'),(14,'Liverpool',24,'Liverpool'),
 (20,'Southampton',25,'Southampton'),(21,'West Ham',40,'West Ham United'),(3,'Arsenal',1,'Arsenal'),
 (31,'Crystal Palace',31,'Crystal Palace'),(35,'West Brom',27,'West Bromwich Albion'),
 (4,'Newcastle',37,'Newcastle United'),(43,'Man City',36,'Manchester City'),(45,'Norwich',56,'Norwich City'),
 (56,'Sunderland',41,'Sunderland'),(57,'Watford',23,'Watford'),(6,'Spurs',38,'Tottenham Hotspur'),
 (7,'Aston Villa',59,'Aston Villa'),(8,'Chelsea',33,'Chelsea'),(80,'Swansea',26,'Swansea City'),
 (91,'Bournemouth',28,'AFC Bournemouth')]


def unique_pair_index(rows):
    result={}
    for row in rows:
        key=(int(row['home_team_id']),int(row['away_team_id']))
        if key[0]==key[1] or key in result:raise ValueError('ambiguous or invalid directed club pair')
        result[key]=row
    return result


def score(value):
    if value in ('',None):return None
    number=float(value)
    if not number.is_integer() or number<0:raise ValueError('invalid goal count')
    return int(number)


def build(statsbomb_root,archive_root,package,out):
    sb_manifest_bytes=(statsbomb_root/'manifest.json').read_bytes();sb_manifest=json.loads(sb_manifest_bytes)
    records=[r for r in sb_manifest['records'] if r['path']=='data/matches/2/27.json']
    if len(records)!=1:raise ValueError('ambiguous StatsBomb calendar')
    sb_matches=json.loads(read_record(statsbomb_root,records[0]));sb_sha=records[0]['sha256']
    manifest_bytes=(archive_root/'manifest.json').read_bytes();manifest=json.loads(manifest_bytes)
    refs=[r for r in manifest['records'] if r['repository']=='imadeddine-belkat/Premier-League-Stats' and r['path']=='pl_stats/_merged/events/2015-16_events_stats.csv']
    if len(refs)!=1:raise ValueError('ambiguous archive calendar')
    body=checked(archive_root/'objects'/refs[0]['sha256'],refs[0]['sha256'])
    archive=list(csv.DictReader(io.StringIO(body.decode())))
    if {r['season'] for r in archive}!={'2015-16'}:raise ValueError('unexpected archive season')
    actual_pl={(int(r[side+'_team_id']),r[side+'_team']) for r in archive for side in ('home','away')}
    actual_sb={(r[side+'_team'][side+'_team_id'],r[side+'_team'][side+'_team_name']) for r in sb_matches for side in ('home','away')}
    if actual_pl!={(a,b) for a,b,c,d in CLUBS} or actual_sb!={(c,d) for a,b,c,d in CLUBS}:
        raise ValueError('club mapping not exhaustive or source labels changed')
    club_map={c:a for a,b,c,d in CLUBS};pairs=unique_pair_index(archive)
    sb_pairs=[dict(home_team_id=club_map[r['home_team']['home_team_id']],away_team_id=club_map[r['away_team']['away_team_id']]) for r in sb_matches]
    if set(unique_pair_index(sb_pairs))!=set(pairs):raise ValueError('fixture set mismatch')
    links=[];index={}
    for m in sorted(sb_matches,key=lambda r:r['match_id']):
        pair=(club_map[m['home_team']['home_team_id']],club_map[m['away_team']['away_team_id']]);a=pairs[pair]
        local_date=datetime.fromisoformat(a['kickoff']).date().isoformat()
        goals=(score(a['goalsFor_h']),score(a['goalsFor_a']))
        goal_status='unknown' if None in goals else 'equal' if goals==(m['home_score'],m['away_score']) else 'different'
        row=dict(archive_fixture=int(a['matchId']),statsbomb_match_id=m['match_id'],home_club_code=pair[0],away_club_code=pair[1],
            archive_local_kickoff=a['kickoff'],statsbomb_date=m['match_date'],
            date_status='equal' if local_date==m['match_date'] else 'different',
            archive_score_fields=['goalsFor_h','goalsFor_a'],archive_goals=goals,statsbomb_goals=[m['home_score'],m['away_score']],score_status=goal_status,
            archive_calendar_sha256=refs[0]['sha256'],statsbomb_calendar_sha256=sb_sha,
            research_link_accepted=local_date==m['match_date'],commercial_runtime_admitted=False,training_admitted=False)
        if row['archive_fixture'] in index:raise ValueError('duplicate archive fixture ID')
        index[row['archive_fixture']]=row;links.append(row)
    dataset=verify(package);part=next(p for p in dataset['partitions'] if p['season']=='2015-16')
    labels=list(csv.DictReader(io.StringIO(gzip.decompress(checked(package/part['file'],part['sha256'])).decode())))
    coverage=Counter();date_counts=Counter();issues=[];unique_fixtures=set()
    for row in labels:
        fixture=int(row['fixture']);unique_fixtures.add(fixture);link=index.get(fixture)
        if row['fixture_namespace']!='pl_archive_events':raise ValueError('unexpected GT fixture namespace')
        status='accepted' if link and link['research_link_accepted'] else 'unmatched_or_date_conflict'
        coverage[status]+=1
        value=row.get('event_local_time')
        date_status='missing' if not value else 'equal' if link and value[:10]==link['statsbomb_date'] else 'different'
        date_counts[date_status]+=1
        if status!='accepted' or date_status!='equal':issues.append(dict(element=row['element'],fixture=fixture,status=status,local_date_status=date_status))
    out.mkdir(parents=True,exist_ok=True)
    (out/'fixture-links.json').write_text(json.dumps(links,indent=2)+'\n')
    (out/'label-link-issues.json').write_text(json.dumps(issues,indent=2)+'\n')
    report=dict(version='statsbomb-fixture-crosswalk-v1',dataset_id=dataset['dataset_id'],partition_sha256=part['sha256'],
        statsbomb_manifest_sha256=digest(sb_manifest_bytes),archive_manifest_sha256=digest(manifest_bytes),
        implementation_sha256=digest(Path(__file__).read_bytes()),club_mapping=CLUBS,fixtures=len(links),
        date_status=dict(Counter(r['date_status'] for r in links)),score_status=dict(Counter(r['score_status'] for r in links)),
        GT_rows=len(labels),GT_unique_fixtures=len(unique_fixtures),GT_link_status=dict(coverage),GT_local_date_status=dict(date_counts),
        source_fixtures_without_GT=len(set(index)-unique_fixtures),new_FPL_labels=0,training_admitted=False,
        commercial_runtime_admitted=False,raw_redistribution_admitted=False,production_changed=False,
        limitations=['club_alias_mapping_explicit_not_player_identity_mapping',
            'date_agreement_not_timezone_or_predeadline_publication_proof',
            'research_only_StatsBomb_license_restrictions_inherited',
            'event_semantics_and_player_crosswalk_not_validated'],
        artifacts={n:digest((out/n).read_bytes()) for n in ('fixture-links.json','label-link-issues.json')})
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('statsbomb-root','archive-root','package','out'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.statsbomb_root,a.archive_root,a.package,a.out),indent=2))


if __name__=='__main__':main()
