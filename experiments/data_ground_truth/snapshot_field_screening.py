"""Screen observed fields and publication independently of retrospective labels."""
from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal
import gzip
import json
from pathlib import Path

from experiments.data_ground_truth import bootstrap_performance, publication_selection
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked

INTRO_FIELDS={'starts','expected_goals','expected_assists','expected_goals_conceded','expected_goal_involvements'}


def suspect_zero_fields(rows):
    played=any(r['cells']['minutes']['status']=='valid' and r['cells']['minutes']['value']>0 for r in rows)
    if not played:return set()
    return {f for f in INTRO_FIELDS if all(r['cells'][f]['status']=='valid' and Decimal(str(r['cells'][f]['value']))==0 for r in rows)}


def screen(row,field,published,suspect):
    reasons=[];value=row['cells'][field]
    if not published:reasons.append('publication_unproven')
    if row['gw']==1:reasons.append('GW1_period_unresolved')
    if value['status']!='valid':reasons.append('observed_'+value['status'])
    if field in suspect:reasons.append('population_zero_despite_observed_minutes')
    return dict(status='screen_pass' if not reasons else 'review_required',reasons=reasons)


def build(base,out):
    out.mkdir(parents=True,exist_ok=True)
    # Revalidate publication witnesses and raw numerical extraction, without a GT input.
    selection_root=base/'publication-selection-v1'
    publication_selection.build(base/'publication-alternatives-v1',base/'bootstrap-publication-v1',
                                base/'bootstrap-audit-v1',out/'selection_revalidated')
    for name in ('report.json','nominal_deadline_candidates.json','publication_witnesses.json'):
        if (selection_root/name).read_bytes()!=(out/'selection_revalidated'/name).read_bytes():
            raise ValueError('publication reproduction mismatch')
    perf_root=base/'bootstrap-performance-v2'
    bootstrap_performance.build(base/'raw-bootstrap-snapshots',selection_root,out/'performance_revalidated')
    for name in ('report.json','performance.jsonl.gz','anomalies.json'):
        if (perf_root/name).read_bytes()!=(out/'performance_revalidated'/name).read_bytes():
            raise ValueError('performance reproduction mismatch')
    selection_bytes=(selection_root/'report.json').read_bytes();selection=json.loads(selection_bytes)
    proofs=json.loads(checked(selection_root/'publication_witnesses.json',selection['artifacts']['publication_witnesses.json']))
    proof_map={(p['season'],p['gw']):p for p in proofs}
    if len(proof_map)!=len(proofs):raise ValueError('duplicate proof key')
    perf_bytes=(perf_root/'report.json').read_bytes();perf=json.loads(perf_bytes)
    rows=[json.loads(line) for line in gzip.decompress(checked(perf_root/'performance.jsonl.gz',perf['artifacts']['performance.jsonl.gz'])).splitlines()]
    windows={}
    for row in rows:windows.setdefault((row['season'],row['gw']),[]).append(row)
    output=[];coverage=[]
    for (season,gw),group in sorted(windows.items()):
        proof=proof_map.get((season,gw));suspect=suspect_zero_fields(group)
        counts={f:Counter() for f in bootstrap_performance.FIELDS};reason_counts=Counter()
        for row in group:
            if proof and (proof['source_sha256']!=row['source_sha256'] or proof['deadline']!=row['deadline'] or not proof['eligible_predeadline']):
                raise ValueError('row publication binding mismatch')
            results={f:screen(row,f,proof is not None,suspect) for f in bootstrap_performance.FIELDS}
            for f,v in results.items():counts[f][v['status']]+=1;reason_counts.update(v['reasons'])
            output.append(dict(season=season,gw=gw,element=row['element'],source_sha256=row['source_sha256'],
                               publication_bound=proof['available_at'] if proof else None,
                               fields=results,training_admitted=False))
        coverage.append(dict(season=season,gw=gw,rows=len(group),published=proof is not None,
                             suspicious_population_fields=sorted(suspect),fields={f:dict(c) for f,c in counts.items()},
                             reasons=dict(reason_counts)))
    payload=gzip.compress(('\n'.join(json.dumps(r,sort_keys=True) for r in output)+'\n').encode(),mtime=0)
    (out/'screening.jsonl.gz').write_bytes(payload)
    result=dict(version='snapshot-field-screening-v1',selection_report_sha256=digest(selection_bytes),
                performance_report_sha256=digest(perf_bytes),implementation_sha256=digest(Path(__file__).read_bytes()),
                rows=len(rows),windows=len(windows),coverage=coverage,screening_sha256=digest(payload),
                retrospective_labels_used=False,training_admitted=False,production_changed=False,
                limitations=['screen_pass_is_not_training_or_runtime_admission',
                             'field_semantics_calendar_rules_and_identity_require_separate_contracts',
                             'publication_bound_not_exact_API_capture_time',
                             'population_zero_flag_is_suspicion_not_proof_of_placeholder',
                             'retrospective_agreement_must_never_determine_historical_inclusion'])
    (out/'report.json').write_text(json.dumps(result,indent=2)+'\n');return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('base-root','out'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();r=build(a.base_root,a.out);print(json.dumps(dict(rows=r['rows'],windows=r['windows'])))


if __name__=='__main__':main()
