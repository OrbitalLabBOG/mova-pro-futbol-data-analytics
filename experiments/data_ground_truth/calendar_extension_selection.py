"""Combine freshly revalidated extension witnesses with the prior calendar selection."""
from __future__ import annotations
import argparse
import gzip
import json
from pathlib import Path
from experiments.data_ground_truth import calendar_carryforward as parent
from experiments.data_ground_truth import calendar_publication_extension as extension
from experiments.data_ground_truth import historical_fixture_publication as historical
from experiments.data_ground_truth.bootstrap_time import aware
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked


def build(base:Path,extension_root:Path,out:Path):
    parent_root=base/'calendar-carryforward-v2'
    parent_bytes=(parent_root/'report.json').read_bytes();pr=json.loads(parent_bytes)
    parent.build(base,out/'parent_revalidated',pr['max_addition_nominal_age_hours'])
    for file in ('report.json','selected_calendars.json','deltas.json'):
        if (parent_root/file).read_bytes()!=(out/'parent_revalidated'/file).read_bytes():
            raise ValueError('parent reproduction mismatch')
    audit_bytes,cs=historical.candidates(base/'fixture-history-audit-v1',base/'raw-fixture-history-v1',base/'fixtures-git-provenance')
    candidates={(c['season'],c['gw']):c for c in cs}
    rows=json.loads(checked(parent_root/'selected_calendars.json',pr['artifacts']['selected_calendars.json']))
    known={(r['season'],r['gw']) for r in rows};additions=[];verified={};extension_hashes=[]
    roots=[extension_root] if isinstance(extension_root,Path) else extension_root
    for root in roots:
        er_bytes=(root/'report.json').read_bytes();er=json.loads(er_bytes);extension_hashes.append(digest(er_bytes))
        if er['parent_report_sha256']!=digest(parent_bytes):raise ValueError('extension parent mismatch')
        if er['fixture_audit_sha256']!=digest(audit_bytes):raise ValueError('extension audit mismatch')
        for witness in json.loads(checked(root/'witnesses.json',er['witnesses_sha256'])):
            key=(witness['season'],witness['gw'])
            if key in known:raise ValueError('deadline already selected by parent')
            c=candidates[key];h=witness['archive_hour']
            hour=json.loads(checked(root/'hours'/(h+'.json'),er['hour_report_sha256'][h]));extension.validate(root,hour)
            proof=extension.proof(c,hour,base/'fixtures-git-provenance')
            if proof is None or dict(proof,normalized_sha256=c['normalized_sha256'],source_committer_at=c['committer_at'])!=witness:
                raise ValueError('extension witness mismatch')
            if key not in verified or aware(proof['available_at'])<aware(verified[key]['available_at']):verified[key]=proof
    for key,proof in sorted(verified.items()):
        c=candidates[key]
        age=(aware(c['deadline'])-aware(c['committer_at'])).total_seconds()/3600
        fixtures=json.loads(gzip.decompress(checked(base/'fixture-history-audit-v1/objects'/c['normalized_sha256'],c['normalized_sha256'])))
        row=dict(season=c['season'],gw=c['gw'],deadline=c['deadline'],repository=historical.REPOSITORY,
                 source_committer_at=c['committer_at'],available_at=proof['available_at'],normalized_sha256=c['normalized_sha256'],
                 object_root='fixture-history-audit-v1',proof=proof,selection_kind='extended_publication_witness',
                 nominal_commit_age_hours=age,future_fixture_observations=sum(f['kickoff_time'] is not None and aware(f['kickoff_time'])>aware(c['deadline']) for f in fixtures))
        rows.append(row);known.add(key);additions.append(dict(season=c['season'],gw=c['gw'],nominal_age_hours=age,available_at=proof['available_at']))
    coverage={}
    for r in rows:
        s=coverage.setdefault(r['season'],dict(deadlines=0,within48h=0));s['deadlines']+=1;s['within48h']+=r['nominal_commit_age_hours']<=48
    payload=(json.dumps(sorted(rows,key=lambda r:(r['season'],r['gw'])),indent=2)+'\n').encode();out.mkdir(parents=True,exist_ok=True);(out/'selected_calendars.json').write_bytes(payload)
    result=dict(version='calendar-extension-selection-v1',parent_report_sha256=digest(parent_bytes),extension_report_sha256=extension_hashes,
                implementation_sha256=digest(Path(__file__).read_bytes()),selected_deadlines=len(rows),expected_deadlines=len(cs),coverage=coverage,additions=additions,
                missing=[dict(season=c['season'],gw=c['gw']) for c in cs if (c['season'],c['gw']) not in known],selected_sha256=digest(payload),
                production_changed=False,training_admitted=False,limitations=['publication_not_capture_time','coverage_does_not_guarantee_freshness_or_complete_replay'])
    (out/'report.json').write_text(json.dumps(result,indent=2)+'\n');return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('base-root','out'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--extension-root',type=Path,required=True,action='append')
    a=p.parse_args();print(json.dumps(build(a.base_root,a.extension_root,a.out),indent=2))


if __name__=='__main__':main()
