"""Explain a source-scoped historical player-code conflict without rewriting raw."""
from __future__ import annotations
import argparse
import io
import json
from pathlib import Path
import pandas as pd
from experiments.data_ground_truth.identity_2014 import name_tokens
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked,verify

LATER_SHA='a59256902b2efdc734dc6f86494b54d6cf1e512df90ba14cef95bf03de786865'
PROFILE_SHA='c40f7e6a74160f3a151fb32ee79d5843e87daf58e1a002ccfff412a224804264'
TARGET=name_tokens('Isaiah Brown')


def reference_check(later,profiles,gt):
    if name_tokens(later['first_name']+' '+later['second_name'])!=TARGET:raise ValueError('later name mismatch')
    code=later['code'];matched=profiles.loc[profiles.code.eq(code)]
    if len(matched)!=1 or name_tokens(matched.iloc[0].first_name+' '+matched.iloc[0].second_name)!=TARGET:
        raise ValueError('profile identity ambiguous')
    annual=[h for h in later['season_history'] if h[0]=='2014/15']
    if len(annual)!=1:raise ValueError('annual reference ambiguous')
    rows=gt.loc[gt.element.eq(93)]
    if not len(rows) or rows.official_player_code.isna().any() or set(rows.official_player_code)!={code}:raise ValueError('GT identity mismatch')
    if rows.minutes.sum()!=annual[0][1] or rows.total_points.sum()!=annual[0][-1]:raise ValueError('annual totals mismatch')
    return dict(canonical_code=int(code),season_fpl_id=93,gt_rows=len(rows),minutes=int(rows.minutes.sum()),
                points=int(rows.total_points.sum()),reference_method='full_name_later_profile_and_same_season_annual_totals')


def scoped_links(players,record,canonical):
    if len({p['id'] for p in players})!=len(players):raise ValueError('duplicate source player IDs')
    result=[]
    for p in players:
        full=p['first_name']+' '+p['second_name']
        if p['code'] not in (81132,canonical) and name_tokens(full)!=TARGET:continue
        if name_tokens(full)!=TARGET:raise ValueError('target code belongs to a different name')
        if sum(x['code']==p['code'] for x in players)!=1:raise ValueError('duplicate observed code')
        result.append(dict(source_sha256=record['sha256'],repository=record['repository'],revision=record['revision'],
            source_path=record['path'],source_player_id=p['id'],observed_code=p['code'],source_full_name=full,
            candidate_canonical_code=canonical,code_differs=p['code']!=canonical,
            identity_scope='exact_source_sha_and_source_player_id',available_at=None,
            eligible_training=False,eligible_predeadline=False,global_alias_admitted=False))
    if len(result)>1:raise ValueError('multiple target identities in snapshot')
    return result


def build(base,out):
    later=json.loads(checked(base/'raw-history-2015/objects'/LATER_SHA,LATER_SHA))
    profiles=pd.read_csv(io.BytesIO(checked(base/'raw-history-v2/objects'/PROFILE_SHA,PROFILE_SHA)))
    pointer=json.loads(Path(__file__).with_name('current-labels.json').read_text());package=base/'training-datasets'/pointer['dataset_id']
    checked(package/'manifest.json',pointer['manifest_sha256']);gt=verify(package)
    part=next(x for x in gt['partitions'] if x['season']=='2014-15');rows=pd.read_csv(package/part['file'],compression='gzip')
    reference=reference_check(later,profiles,rows);entries=[];manifests={};raw_records=0;absent=0
    for dirname in ['early-fpl-json-g88','early-fpl-state-history-g88','early-fpl-successor-g90']:
        root=base/dirname;mb=(root/'manifest.json').read_bytes();manifests[dirname]=digest(mb)
        for record in json.loads(mb)['records']:
            if record['path']!='data.json':continue
            payload=checked(root/'objects'/record['sha256'],record['sha256'])
            if len(payload)!=record['bytes']:raise ValueError('raw size mismatch')
            found=scoped_links(json.loads(payload),record,reference['canonical_code']);entries.extend(found);raw_records+=1;absent+=not bool(found)
    # Preserve every provenance receipt; deduplicate only the separate exact-source mapping.
    crosswalk=pd.DataFrame(entries)[['source_sha256','source_player_id','observed_code','candidate_canonical_code','identity_scope','eligible_training','eligible_predeadline','global_alias_admitted']].drop_duplicates()
    if crosswalk.duplicated(['source_sha256','source_player_id']).any():raise ValueError('conflicting scoped identity mapping')
    out.mkdir(parents=True,exist_ok=True)
    (out/'source_identity_evidence.json').write_text(json.dumps(entries,indent=2)+'\n');crosswalk.to_csv(out/'candidate_identity_crosswalk.csv',index=False)
    report=dict(version='early-identity-evidence-v1',manifest_sha256=manifests,later_profile_sha256=LATER_SHA,
        confirmation_profile_sha256=PROFILE_SHA,gt_dataset_id=gt['dataset_id'],gt_manifest_sha256=pointer['manifest_sha256'],
        implementation_sha256=digest(Path(__file__).read_bytes()),reference=reference,raw_records_checked=raw_records,
        target_absent_records=absent,evidence_records=len(entries),unique_source_mappings=len(crosswalk),
        observed_codes=sorted(int(x) for x in crosswalk.observed_code.unique()),
        differing_code_mappings=int(crosswalk.observed_code.ne(reference['canonical_code']).sum()),
        global_alias_admitted=False,training_admitted=False,source_labels_modified=False,production_changed=False,
        limitations=['corroborated_candidate_not_universal_alias','no_exact_code_change_date_or_cause_proven',
                     'annual_total_agreement_not_independent_match_label_recovery','raw_observed_codes_remain_unchanged','references_may_overlap_existing_GT_identity_provenance'],
        artifacts={n:digest((out/n).read_bytes()) for n in ['source_identity_evidence.json','candidate_identity_crosswalk.csv']})
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.base,a.out),indent=2))
