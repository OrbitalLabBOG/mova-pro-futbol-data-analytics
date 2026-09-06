"""Materialize auditable snapshot selection from original and alternative push witnesses."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from experiments.data_ground_truth.publication_alternatives import verify_hour
from experiments.data_ground_truth.publication_archive import witness
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked


def evidence(root,report,candidate,proof):
    hour=proof['archive_hour']
    record=json.loads(checked(root/'hours'/(hour+'.json'),report['hour_report_sha256'][hour]))
    verify_hour(root,record)
    if witness(candidate,record)!=proof or not proof['eligible_predeadline']:
        raise ValueError('selection witness mismatch')


def build(alternatives_root:Path,original_archive_root:Path,original_audit_root:Path,out:Path):
    alternative_bytes=(alternatives_root/'report.json').read_bytes()
    alternative=json.loads(alternative_bytes)
    plan=json.loads(checked(alternatives_root/'plan.json',alternative['plan_sha256']))
    original_archive=json.loads(checked(original_archive_root/'report.json',plan['archive_report_sha256']))
    if original_archive['git_provenance_report_sha256']!=plan['provenance_report_sha256']:
        raise ValueError('original provenance mismatch')
    found=json.loads(checked(alternatives_root/'found.json',alternative['artifacts']['found.json']))
    unresolved=json.loads(checked(alternatives_root/'unresolved.json',alternative['artifacts']['unresolved.json']))
    audit_bytes=(original_audit_root/'report.json').read_bytes();audit=json.loads(audit_bytes)
    if audit['manifest_sha256']!=plan['source_manifest_sha256'] or audit['errors']:
        raise ValueError('original audit mismatch')
    originals=json.loads(checked(original_audit_root/'nominal_deadline_candidates.json',audit['artifacts']['nominal_deadline_candidates.json']))
    key=lambda c:(c['season'],c['gw'])
    selected={key(c):c for c in originals}
    jobs={key(j['original']):j for j in plan['jobs']}
    if len(selected)!=len(originals) or len(selected)!=plan['original_candidates']:
        raise ValueError('original candidate count mismatch')
    proofs={}
    for item in plan['preserved']+found:
        c,p=item['candidate'],item['witness'];k=key(c)
        if k in proofs or k not in selected:
            raise ValueError('duplicate or unknown selected deadline')
        if item in found:
            if k not in jobs or c not in jobs[k]['alternatives']:
                raise ValueError('unplanned alternative')
            evidence(alternatives_root,alternative,c,p)
            selected[k]=dict(season=c['season'],gw=c['gw'],deadline=c['deadline'],
                source_claimed_at=c['source_claimed_at'],path=c['path'],sha256=c['source_sha256'],eligible_predeadline=False)
        else:
            if selected[k]['sha256']!=c['source_sha256'] or selected[k]['path']!=c['path'] or selected[k]['deadline']!=c['deadline']:
                raise ValueError('preserved original mismatch')
            evidence(original_archive_root,original_archive,c,p)
        proofs[k]=p
    missing=set(selected)-set(proofs)
    if missing!={key(c) for c in unresolved} or len(found)!=alternative['new_witnesses'] or len(plan['preserved'])!=alternative['preserved_witnesses']:
        raise ValueError('selection partition mismatch')
    out.mkdir(parents=True,exist_ok=True)
    artifacts={}
    for name,value in [('nominal_deadline_candidates.json',[selected[k] for k in sorted(selected)]),
                       ('publication_witnesses.json',[proofs[k] for k in sorted(proofs)])]:
        payload=(json.dumps(value,indent=2)+'\n').encode();(out/name).write_bytes(payload);artifacts[name]=digest(payload)
    seasons={season:dict(candidates=sum(k[0]==season for k in selected),verified_deadlines=sum(k[0]==season for k in proofs),
        changed_snapshots=sum(x['candidate']['season']==season for x in found)) for season in sorted({k[0] for k in selected})}
    report=dict(version='publication-selection-v1',manifest_sha256=plan['source_manifest_sha256'],errors=[],
        alternatives_report_sha256=digest(alternative_bytes),original_audit_report_sha256=digest(audit_bytes),
        implementation_sha256=digest(Path(__file__).read_bytes()),artifacts=artifacts,candidates=len(selected),
        verified_deadlines=len(proofs),replaced_snapshots=len(found),unresolved_deadlines=len(missing),seasons=seasons,
        max_extra_staleness_hours=max((x['extra_staleness_hours'] for x in found),default=0),
        min_extra_staleness_hours=min((x['extra_staleness_hours'] for x in found),default=0),
        scope='snapshot_selection_only_not_training_admission',training_admitted=False,production_changed=False,
        acquisition_errors=alternative['errors'])
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('alternatives-root','original-archive-root','original-audit-root','out'):
        ap.add_argument('--'+name,type=Path,required=True)
    args=ap.parse_args()
    print(json.dumps(build(args.alternatives_root,args.original_archive_root,args.original_audit_root,args.out),indent=2))


if __name__=='__main__':main()
