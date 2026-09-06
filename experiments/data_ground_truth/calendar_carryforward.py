"""Reuse previously published whole calendars with explicit age and retrospective deltas."""
from __future__ import annotations

import argparse
from collections import Counter
import gzip
import json
from pathlib import Path

from experiments.data_ground_truth import calendar_publication_selection as parent
from experiments.data_ground_truth.bootstrap_time import aware
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked


def select_previous(rows, target, max_age_hours=336):
    if max_age_hours <= 0:
        raise ValueError('positive age bound required')
    valid = []
    for row in rows:
        if row['season'] != target['season'] or row['gw'] >= target['gw']:
            continue
        age = (aware(target['deadline'])-aware(row['source_committer_at'])).total_seconds()/3600
        if (row['proof']['eligible_predeadline'] and 0 < age <= max_age_hours and
                aware(row['source_committer_at']) <= aware(row['available_at']) < aware(row['deadline']) < aware(target['deadline'])):
            valid.append(row)
    return max(valid, key=lambda r:(aware(r['source_committer_at']),r['repository'],r['gw'])) if valid else None


def differences(old, newer, deadline):
    by_old = {f['id']:f for f in old}; by_new = {f['id']:f for f in newer}
    if len(by_old) != len(old) or len(by_new) != len(newer) or by_old.keys() != by_new.keys():
        raise ValueError('fixture population mismatch')
    result=[]
    for key in sorted(by_old):
        a,b=by_old[key],by_new[key]
        if any(a[f]!=b[f] for f in ('code','team_h','team_a')):
            raise ValueError('fixture identity mismatch')
        for field in ('event','kickoff_time'):
            if a[field]!=b[field]:
                future=any(f['kickoff_time'] is None or aware(f['kickoff_time'])>aware(deadline) for f in (a,b))
                result.append(dict(fixture=key,field=field,carried_value=a[field],later_unproven_value=b[field],future_or_unknown=future))
    return result


def build(base:Path,out:Path,max_age_hours=336):
    original=base/'calendar-publication-selection-v1'
    out.mkdir(parents=True,exist_ok=True)
    parent.build(base,out/'parent_revalidated')
    for file in ('report.json','selected_calendars.json'):
        if (original/file).read_bytes()!=(out/'parent_revalidated'/file).read_bytes():
            raise ValueError('parent reproduction mismatch')
    report_bytes=(original/'report.json').read_bytes();report=json.loads(report_bytes)
    selected=json.loads(checked(original/'selected_calendars.json',report['selected_sha256']))
    audit=json.loads((base/'fixture-history-audit-v1/report.json').read_text())
    candidates=json.loads(checked(base/'fixture-history-audit-v1/nominal_candidates.json',audit['artifacts']['nominal_candidates.json']))
    keys={(r['season'],r['gw']) for r in selected};rows=list(selected);additions=[];deltas=[]
    def fixtures(root,sha):
        return json.loads(gzip.decompress(checked(base/root/'objects'/sha,sha)))
    for target in candidates:
        if (target['season'],target['gw']) in keys:
            continue
        # Always choose from independently revalidated parent evidence, not chained imputations.
        previous=select_previous(selected,target,max_age_hours)
        if previous is None:
            continue
        old=fixtures(previous['object_root'],previous['normalized_sha256'])
        later=fixtures('fixture-history-audit-v1',target['normalized_sha256'])
        delta=differences(old,later,target['deadline'])
        age=(aware(target['deadline'])-aware(previous['source_committer_at'])).total_seconds()/3600
        row=dict(previous,gw=target['gw'],deadline=target['deadline'],origin_gw=previous['gw'],
                 origin_deadline=previous['deadline'],nominal_commit_age_hours=age,
                 selection_kind='previously_published_whole_calendar',
                 future_fixture_observations=sum(f['kickoff_time'] is not None and aware(f['kickoff_time'])>aware(target['deadline']) for f in old))
        rows.append(row);keys.add((row['season'],row['gw']))
        additions.append(dict(season=row['season'],gw=row['gw'],origin_gw=row['origin_gw'],
                              nominal_age_hours=age,available_at=row['available_at'],normalized_sha256=row['normalized_sha256'],
                              changed_fields=len(delta),future_or_unknown_changed_fields=sum(d['future_or_unknown'] for d in delta)))
        deltas.append(dict(season=row['season'],gw=row['gw'],later_unproven_sha256=target['normalized_sha256'],changes=delta))
    coverage={}
    for row in rows:
        s=coverage.setdefault(row['season'],dict(deadlines=0,within48h=0))
        s['deadlines']+=1;s['within48h']+=row['nominal_commit_age_hours']<=48
    artifacts={}
    for file,data in [('selected_calendars.json',sorted(rows,key=lambda r:(r['season'],r['gw']))),('deltas.json',deltas)]:
        payload=(json.dumps(data,indent=2)+'\n').encode();(out/file).write_bytes(payload);artifacts[file]=digest(payload)
    result=dict(version='calendar-carryforward-v1',parent_report_sha256=digest(report_bytes),
                implementation_sha256=digest(Path(__file__).read_bytes()),max_addition_nominal_age_hours=max_age_hours,
                expected_deadlines=len(candidates),parent_deadlines=len(selected),selected_deadlines=len(rows),
                additions=additions,coverage=coverage,
                missing=[dict(season=c['season'],gw=c['gw']) for c in candidates if (c['season'],c['gw']) not in keys],
                delta_fields=dict(Counter(d['field'] for r in deltas for d in r['changes'])),artifacts=artifacts,
                production_changed=False,training_admitted=False,
                limitations=['carryforward_does_not_increase_source_sampling_freshness',
                             'later_unproven_values_are_diagnostics_not_features',
                             'age_bound_is_experimental_not_replay_readiness'])
    (out/'report.json').write_text(json.dumps(result,indent=2)+'\n');return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base-root',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);p.add_argument('--max-age-hours',type=int,default=336)
    a=p.parse_args();print(json.dumps(build(a.base_root,a.out,a.max_age_hours),indent=2))


if __name__=='__main__':main()
