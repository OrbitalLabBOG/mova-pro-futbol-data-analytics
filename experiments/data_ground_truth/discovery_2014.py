"""Reconcile public 2014/15 CSV and retain explicit code candidates without GT mutation."""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
import csv
from decimal import Decimal, InvalidOperation
import io
import gzip
import json
from pathlib import Path

from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked,verify

NUMERIC={'M':'mins','G':'goals','A':'assists','CS':'cs','GC':'ga','OG':'og','PS':'pens_svd',
         'PM':'pens_msd','YC':'yel','RC':'red','S':'saves','B':'bonus','ESP':'ea_ppi','BPS':'bps',
         'NT':'net_transfers','P':'gw_pts','total_points':'final_season_points','selected_by':'final_season_ownership',
         'V':'gw_val','now_cost':'final_season_value'}
TEXT={'web_name':'name','type_name':'pos','team_name':'final_season_team'}
PROFILE=('code','web_name','first_name','second_name','type_name','team_name','status','selected_by','transfers_in','transfers_out','now_cost','total_points')


def number(value):
    try: result=Decimal(str(value).replace(',','.'))
    except InvalidOperation as exc:raise ValueError('invalid numeric cell') from exc
    if not result.is_finite():raise ValueError('nonfinite numeric cell')
    return result


def integer(value):
    n=number(value)
    if n!=n.to_integral_value() or n<=0:raise ValueError('positive integer required')
    return int(n)


def key(row,raw):
    return (integer(row['id']),integer(row['GW' if raw else 'gw']),row['date'],row['fixture' if raw else 'opp'])


def reconcile(source,reference):
    left={key(r,True):r for r in source};right={key(r,False):r for r in reference}
    if len(left)!=len(source) or len(right)!=len(reference):raise ValueError('duplicate player fixture source key')
    shared=left.keys()&right.keys();differences=[];profiles={};codes={}
    for k,row in left.items():
        pid=k[0];profile={f:row[f] for f in PROFILE};code=integer(row['code'])
        if pid in profiles and profiles[pid]!=profile:raise ValueError('inconsistent player profile')
        if code in codes and codes[code]!=pid:raise ValueError('code assigned to multiple players')
        profiles[pid]=profile;codes[code]=pid
    for k in sorted(shared):
        a,b=left[k],right[k]
        for field,other in NUMERIC.items():
            v=number(a[field])/(10 if field in ('V','now_cost') else 1)
            if v!=number(b[other]):differences.append(dict(key=k,field=field,source=a[field],reference=b[other]))
        for field,other in TEXT.items():
            if a[field]!=b[other]:differences.append(dict(key=k,field=field,source=a[field],reference=b[other]))
    identity=[];refcodes=defaultdict(set);counts=Counter();played=Counter()
    for r in reference:
        pid=integer(r['id']);counts[pid]+=1;played[pid]+=number(r['mins'])>0
        if r['official_player_code']:refcodes[pid].add(integer(r['official_player_code']))
    for pid,profile in sorted(profiles.items()):
        known=refcodes[pid];code=integer(profile['code'])
        if len(known)>1:raise ValueError('conflicting reference codes')
        status='agrees_existing_code' if known=={code} else ('conflicts_existing_code' if known else 'new_source_code_candidate')
        identity.append(dict(player_id=pid,source_code=code,reference_codes=sorted(known),status=status,
                             reference_rows=counts[pid],played_rows=played[pid],profile=profile,
                             profile_time_semantics='final_season_snapshot_not_predeadline_features',
                             available_at=None,eligible_training=False))
    summary=dict(source_rows=len(source),reference_rows=len(reference),shared_rows=len(shared),
                 new_keys=len(left.keys()-right.keys()),missing_keys=len(right.keys()-left.keys()),
                 compared_cells=len(shared)*(len(NUMERIC)+len(TEXT)),cell_disagreements=len(differences),
                 source_players=len(profiles),identity_status=dict(Counter(r['status'] for r in identity)))
    return identity,differences,summary


def corroborate(identities,reference,observations):
    # Published source codes are compared with played club-fixture records, not inferred from names.
    lookup=defaultdict(set)
    for r in observations:
        if r['official_player_code'] and r['minutesPlayed'].strip() and number(r['minutesPlayed'])>0:
            lookup[(integer(r['official_player_code']),integer(r['matchId_events']))].add(integer(r['team_id']))
    by_player=defaultdict(list)
    for r in reference:by_player[integer(r['id'])].append(r)
    for identity in identities:
        matches=set();conflicts=set();absent=set()
        for r in by_player[identity['player_id']]:
            if number(r['mins'])<=0:continue
            fixture=integer(r['matchId']);teams=lookup.get((identity['source_code'],fixture),set())
            if not teams:absent.add(fixture)
            elif teams=={integer(r['match_team_code'])}:matches.add(fixture)
            else:conflicts.add(fixture)
        identity['played_fixture_evidence']=dict(matching=sorted(matches),conflicting=sorted(conflicts),absent=sorted(absent))
        identity['two_played_fixture_corroboration']=len(matches)>=2 and not conflicts
    return dict(observation_rows_without_minutes=sum(not r['minutesPlayed'].strip() for r in observations),
                new_candidates_with_two_played_fixtures=sum(r['status']=='new_source_code_candidate' and r['two_played_fixture_corroboration'] for r in identities),
                candidates_with_conflicting_played_fixtures=sum(bool(r['played_fixture_evidence']['conflicting']) for r in identities),
                new_candidate_rows=sum(r['reference_rows'] for r in identities if r['status']=='new_source_code_candidate'))


GT_ID='1d111a458c9074fcd7ec2da516e82d9d1984600f6f057716112b92e855240df4'
GT_FIELDS={'M':'minutes','G':'goals_scored','A':'assists','CS':'clean_sheets','GC':'goals_conceded',
           'OG':'own_goals','PS':'penalties_saved','PM':'penalties_missed','YC':'yellow_cards',
           'RC':'red_cards','S':'saves','B':'bonus','BPS':'bps','P':'total_points','GW':'gw'}


def compare_gt(identities,source,reference,gt_rows):
    by_raw={key(r,True):r for r in source};by_gt={(integer(r['element']),integer(r['fixture'])):r for r in gt_rows}
    if len(by_gt)!=len(gt_rows):raise ValueError('duplicate GT player fixture')
    refkeys={(integer(r['id']),integer(r['matchId'])) for r in reference}
    if refkeys!=by_gt.keys():raise ValueError('GT label population mismatch')
    codes=defaultdict(set);counts=Counter();played=Counter();diff=[]
    for r in reference:
        pid=integer(r['id']);g=by_gt[(pid,integer(r['matchId']))];a=by_raw[key(r,False)]
        counts[pid]+=1;played[pid]+=number(g['minutes'])>0
        if g['official_player_code']:codes[pid].add(integer(g['official_player_code']))
        for source_field,gt_field in GT_FIELDS.items():
            if number(a[source_field])!=number(g[gt_field]):diff.append(dict(player_id=pid,fixture=integer(g['fixture']),field=gt_field,source=a[source_field],gt=g[gt_field]))
    for identity in identities:
        pid=identity['player_id'];known=codes[pid]
        if len(known)>1:raise ValueError('ambiguous GT player code')
        identity['gt_v5_codes']=sorted(known)
        identity['gt_v5_status']='agrees_existing_code' if known=={identity['source_code']} else ('conflicts_existing_code' if known else 'new_source_code_candidate')
    candidates=[r for r in identities if r['gt_v5_status']=='new_source_code_candidate']
    return dict(identity_status=dict(Counter(r['gt_v5_status'] for r in identities)),
                new_candidate_rows=sum(counts[r['player_id']] for r in candidates),
                new_candidate_played_rows=sum(played[r['player_id']] for r in candidates),
                new_candidates_with_two_played_fixtures=sum(r['two_played_fixture_corroboration'] for r in candidates),
                compared_cells=len(reference)*len(GT_FIELDS),cell_disagreements=len(diff)),diff


def build(base,out):
    root=base/'raw-fpl-discovery-v1';record_bytes=(root/'points-2014-15.csv.json').read_bytes();record=json.loads(record_bytes)
    data=checked(root/'points-2014-15.csv',record['sha256'])
    if len(data)!=record['bytes']:raise ValueError('raw size mismatch')
    refroot=base/'raw-history-2014/identity';refbytes=(refroot/'report.json').read_bytes();ref=json.loads(refbytes)
    refdata=checked(refroot/'labels.csv',ref['labels_sha256'])
    read=lambda b:list(csv.DictReader(io.StringIO(b.decode('utf-8-sig'))))
    reference=read(refdata);identities,differences,summary=reconcile(read(data),reference)
    obsroot=base/'raw-history-v2';obsreport_bytes=(obsroot/'crosswalk-report.json').read_bytes();obsreport=json.loads(obsreport_bytes)
    obsdata=checked(obsroot/'crosswalk/2014-15/player_match_observations.csv',obsreport['seasons']['2014-15']['observation_sha256'])
    extra=corroborate(identities,reference,read(obsdata))
    package=base/'training-datasets'/GT_ID;verify(package)
    gt_manifest_bytes=(package/'manifest.json').read_bytes();gt_manifest=json.loads(gt_manifest_bytes)
    partition=next(p for p in gt_manifest['partitions'] if p['season']=='2014-15')
    gtdata=checked(package/partition['file'],partition['sha256'])
    current,gt_differences=compare_gt(identities,read(data),reference,read(gzip.decompress(gtdata)))
    out.mkdir(parents=True,exist_ok=True);artifacts={}
    for name,value in [('identity-candidates.json',identities),('cell-disagreements.json',differences),('gt-cell-disagreements.json',gt_differences)]:
        payload=(json.dumps(value,indent=2)+'\n').encode();(out/name).write_bytes(payload);artifacts[name]=digest(payload)
    report=dict(version='discovery-2014-reconciliation-v1',source_record_sha256=digest(record_bytes),source_csv_sha256=digest(data),
                reference_report_sha256=digest(refbytes),reference_csv_sha256=digest(refdata),
                observation_report_sha256=digest(obsreport_bytes),observation_csv_sha256=digest(obsdata),
                implementation_sha256=digest(Path(__file__).read_bytes()),**summary,**extra,artifacts=artifacts,
                reference_scope='original_identity_baseline_before_GT_v5',
                gt_v5_comparison=dict(dataset_id=GT_ID,manifest_sha256=digest(gt_manifest_bytes),partition_sha256=digest(gtdata),**current),
                production_changed=False,gt_v5_changed=False,training_admitted=False,
                limitations=['source_lineage_may_be_shared_not_independent_truth_votes',
                             'source_codes_are_candidates_not_automatic_GT_replacements',
                             'final_season_profile_fields_are_not_historical_features'])
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base-root',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    print(json.dumps(build(a.base_root,a.out),indent=2))


if __name__=='__main__':main()
