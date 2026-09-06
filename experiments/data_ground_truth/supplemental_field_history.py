"""Trace presence, zero-only populations and numerical precision in raw snapshots."""
from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal
import json
from pathlib import Path

from experiments.data_ground_truth.bootstrap_audit import decode, inspect
from experiments.data_ground_truth.bootstrap_performance import cell
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked

FIELDS=('starts','expected_goals','expected_assists','expected_goals_conceded','expected_goal_involvements')


def profile(elements,field):
    values=[cell(e,field) for e in elements]
    counts=Counter(v['status'] for v in values)
    valid=[Decimal(str(v['value'])) for v in values if v['status']=='valid']
    positive=sum(v>0 for v in valid)
    subcent=sum(v*100!=(v*100).to_integral_value() for v in valid)
    if counts.get('absent')==len(elements):regime='absent'
    elif len(valid)!=len(elements):regime='partial_or_invalid'
    elif not positive:regime='all_zero'
    elif subcent:regime='positive_subcent_precision'
    else:regime='positive_hundredth_compatible'
    return dict(regime=regime,statuses=dict(counts),positive=positive,zero=len(valid)-positive,
                subcent_precision=subcent,players=len(elements))


def build(raw_root,audit_root,out,season='2022-23'):
    manifest_bytes=(raw_root/'manifest.json').read_bytes();manifest=json.loads(manifest_bytes)
    audit_bytes=(audit_root/'report.json').read_bytes();audit=json.loads(audit_bytes)
    if audit['manifest_sha256']!=digest(manifest_bytes) or audit['errors'] or manifest['errors']:
        raise ValueError('source audit binding invalid')
    inventory=json.loads(checked(audit_root/'snapshot_audit.json',audit['artifacts']['snapshot_audit.json']))
    records={r['path']:r for r in manifest['records']};observations=[]
    for item in sorted(inventory,key=lambda r:(r['source_claimed_at'],r['path'])):
        if item['season']!=season:continue
        record=records[item['path']]
        if record['sha256']!=item['sha256']:raise ValueError('object binding mismatch')
        payload=checked(raw_root/'objects'/item['sha256'],item['sha256'])
        if len(payload)!=record['bytes']:raise ValueError('object size mismatch')
        snapshot=decode(payload);actual,_=inspect(snapshot,item['path'])
        if actual['season']!=season or actual['source_claimed_at']!=item['source_claimed_at']:
            raise ValueError('snapshot context mismatch')
        players=[e for e in snapshot['elements'] if e['element_type'] in (1,2,3,4)]
        if not players:raise ValueError('empty player population')
        observations.append(dict(source_path=item['path'],source_sha256=item['sha256'],
                                 source_claimed_at=item['source_claimed_at'],available_at=None,
                                 fields={f:profile(players,f) for f in FIELDS}))
    if not observations:raise ValueError('no season snapshots')
    summaries={}
    for field in FIELDS:
        transitions=[]
        for before,after in zip(observations,observations[1:]):
            if before['fields'][field]['regime']!=after['fields'][field]['regime']:
                transitions.append(dict(before_claimed_at=before['source_claimed_at'],after_claimed_at=after['source_claimed_at'],
                                        before_sha256=before['source_sha256'],after_sha256=after['source_sha256'],
                                        before=before['fields'][field],after=after['fields'][field]))
        summaries[field]=dict(regimes=dict(Counter(r['fields'][field]['regime'] for r in observations)),transitions=transitions)
    out.mkdir(parents=True,exist_ok=True)
    data=(json.dumps(observations,indent=2)+'\n').encode();(out/'observations.json').write_bytes(data)
    result=dict(version='supplemental-field-history-v1',season=season,source_manifest_sha256=digest(manifest_bytes),
                source_audit_sha256=digest(audit_bytes),implementation_sha256=digest(Path(__file__).read_bytes()),
                snapshots=len(observations),first_claimed_at=observations[0]['source_claimed_at'],
                last_claimed_at=observations[-1]['source_claimed_at'],summaries=summaries,observations_sha256=digest(data),
                training_admitted=False,production_changed=False,
                limitations=['source_clock_not_publication_or_exact_API_change_time',
                             'all_zero_is_observation_not_proven_placeholder',
                             'precision_compatibility_not_proven_rounding_policy',
                             'no_reference_values_backfilled_into_snapshots'])
    (out/'report.json').write_text(json.dumps(result,indent=2)+'\n');return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('raw-root','audit-root','out'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--season',default='2022-23')
    a=p.parse_args();r=build(a.raw_root,a.audit_root,a.out,a.season);print(json.dumps(dict(snapshots=r['snapshots'])))


if __name__=='__main__':main()
