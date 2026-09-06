"""Compare supplemental totals using exact decimals and explicit rounding hypotheses."""
from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal
import gzip
import json
from pathlib import Path

from experiments.data_ground_truth.bootstrap_performance import EXPECTED
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.supplemental_components import FIELDS, instant
from experiments.data_ground_truth.training_dataset import checked


def compare(observed, total, count, unknown, two_decimal, field):
    if observed['status'] != 'valid':
        return dict(status='snapshot_'+observed['status'])
    if not count:
        return dict(status='no_reference_rows')
    if unknown:
        return dict(status='unknown_reference_component')
    value = Decimal(str(observed['value']))
    delta = value-total
    if not delta:
        return dict(status='equal')
    result = dict(delta=str(delta),snapshot_value=str(value),final_reference_total=str(total))
    if field in EXPECTED and two_decimal and value*100 == (value*100).to_integral_value():
        # Assumption: every match and the cumulative value rounded to nearest 0.01.
        bound = Decimal('0.005')*(count+1)
        result.update(rounding_bound=str(bound),status='within_rounding_bound' if abs(delta)<=bound else 'outside_rounding_bound')
    else:
        result['status']='different'
    return result


def build(supplemental_root, performance_root, out):
    report_bytes=(supplemental_root/'report.json').read_bytes();report=json.loads(report_bytes)
    match_data=checked(supplemental_root/'components.jsonl.gz',report['artifacts']['components.jsonl.gz'])
    matches=[json.loads(line) for line in gzip.decompress(match_data).splitlines()]
    perf_bytes=(performance_root/'report.json').read_bytes();perf=json.loads(perf_bytes)
    snapshot_data=checked(performance_root/'performance.jsonl.gz',perf['artifacts']['performance.jsonl.gz'])
    snapshots=[json.loads(line) for line in gzip.decompress(snapshot_data).splitlines()]
    keys=[(r['season'],r['gw'],r['element']) for r in snapshots]
    if len(keys)!=len(set(keys)):raise ValueError('duplicate snapshot key')
    match_keys=[(r['season'],r['element'],r['fixture']) for r in matches]
    if len(match_keys)!=len(set(match_keys)):raise ValueError('duplicate reference key')
    # A quarantined/missing row can make a player's cumulative sum incomplete.
    # This gate compares only seasons with complete player reference linkage.
    complete={s for s,c in report['coverage'].items() if c['reference_rows']>0 and
              c['statuses'].get('linked',0)==c['reference_rows']}
    output=[];coverage={}
    for season in sorted({r['season'] for r in snapshots}):
        if season not in complete:
            coverage[season]=dict(status='incomplete_reference_season')
            continue
        selected=[r for r in snapshots if r['season']==season and r['gw']>1]
        history=sorted([r for r in matches if r['season']==season],key=lambda r:(instant(r['event_time_utc']),r['element'],r['fixture']))
        state={};cursor=0;windows=[];previous_cutoff=None
        for gw in sorted({r['gw'] for r in selected}):
            rows=[r for r in selected if r['gw']==gw];deadlines={r['deadline'] for r in rows}
            if len(deadlines)!=1:raise ValueError('inconsistent deadline')
            deadline=deadlines.pop();cutoff=instant(deadline)
            if cutoff is None or (previous_cutoff is not None and cutoff<=previous_cutoff):
                raise ValueError('deadlines must increase')
            previous_cutoff=cutoff
            while cursor<len(history) and instant(history[cursor]['event_time_utc'])<cutoff:
                r=history[cursor];cursor+=1
                key=(r['element'],str(r['official_player_code']))
                entry=state.setdefault(key,{f:dict(total=Decimal(0),count=0,unknown=False,two_decimal=True) for f in FIELDS})
                for field,acc in entry.items():
                    acc['count']+=1;v=r['cells'][field]
                    if v['status']!='valid':acc['unknown']=True;continue
                    number=Decimal(str(v['value']));acc['total']+=number
                    acc['two_decimal'] &= number*100==(number*100).to_integral_value()
            counters={f:Counter() for f in FIELDS}
            for row in rows:
                key=(row['element'],str(row['source_code']));entry=state.get(key,{})
                comparisons={}
                for field in FIELDS:
                    acc=entry.get(field,dict(total=Decimal(0),count=0,unknown=False,two_decimal=True))
                    verdict=compare(row['cells'][field],field=field,**acc)
                    comparisons[field]=verdict;counters[field][verdict['status']]+=1
                output.append(dict(season=season,gw=gw,element=row['element'],source_code=row['source_code'],
                                   source_sha256=row['source_sha256'],deadline=deadline,comparisons=comparisons))
            windows.append(dict(gw=gw,rows=len(rows),fields={f:dict(c) for f,c in counters.items()}))
        coverage[season]=dict(status='compared',windows=windows)
    out.mkdir(parents=True,exist_ok=True)
    payload=gzip.compress(('\n'.join(json.dumps(r,sort_keys=True) for r in output)+'\n').encode(),mtime=0)
    (out/'comparisons.jsonl.gz').write_bytes(payload)
    result=dict(version='supplemental-cumulative-v1',supplemental_report_sha256=digest(report_bytes),
                performance_report_sha256=digest(perf_bytes),dataset_id=report['dataset_id'],
                implementation_sha256=digest(Path(__file__).read_bytes()),rows=len(output),coverage=coverage,
                comparisons_sha256=digest(payload),training_admitted=False,production_changed=False,
                limitations=['final_match_values_not_historical_versions',
                             'within_rounding_bound_is_hypothesis_not_semantic_equality',
                             'rounding_bound_assumes_nearest_hundredth_for_each_match_and_cumulative_value',
                             'kickoff_before_deadline_not_settlement_or_publication_proof',
                             'source_code_and_element_match_not_independent_identity_proof',
                             'GW1_excluded_and_incomplete_reference_seasons_not_compared'])
    (out/'report.json').write_text(json.dumps(result,indent=2)+'\n');return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('supplemental-root','performance-root','out'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();r=build(a.supplemental_root,a.performance_root,a.out);print(json.dumps(dict(rows=r['rows'])) )


if __name__=='__main__':main()
