"""Separate historical calendar availability from staleness and diagnostic horizon changes."""
from __future__ import annotations
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
from experiments.data_ground_truth import calendar_publication_selection as parent
from experiments.data_ground_truth.calendar_carryforward import differences
from experiments.data_ground_truth.bootstrap_time import aware
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked

TARGETS={('2021-22',31),('2021-22',32),('2022-23',23),('2026-27',1)}


def previous(rows,target):
    candidates=[r for r in rows if r['season']==target['season'] and r['gw']<target['gw']
        and r['proof']['eligible_predeadline'] is True
        and aware(r['source_committer_at'])<=aware(r['available_at'])<aware(r['deadline'])<aware(target['deadline'])]
    return max(candidates,key=lambda r:(aware(r['source_committer_at']),r['repository'],r['gw'])) if candidates else None


def horizon_changes(old,later,gw,horizon=6):
    clubs=sorted({f[k] for f in old for k in ('team_h','team_a')})
    def counts(fixtures):
        result=Counter()
        for f in fixtures:
            event=f['event']
            if event is not None and gw<=event<min(gw+horizon,39):
                for k in ('team_h','team_a'):result[(f[k],event)]+=1
        return result
    a,b=counts(old),counts(later)
    return [dict(club=club,gw=week,observed_older_count=a[club,week],later_unproven_count=b[club,week])
        for week in range(gw,min(gw+horizon,39)) for club in clubs if a[club,week]!=b[club,week]]


def build(base,out):
    source=base/'calendar-publication-selection-v1';out.mkdir(parents=True,exist_ok=True)
    parent.build(base,out/'parent_revalidated')
    for name in ('report.json','selected_calendars.json'):
        if (source/name).read_bytes()!=(out/'parent_revalidated'/name).read_bytes():raise ValueError('publication parent differs')
    report_bytes=(source/'report.json').read_bytes();report=json.loads(report_bytes)
    rows=json.loads(checked(source/'selected_calendars.json',report['selected_sha256']))
    audit_bytes=(base/'fixture-history-audit-v1/report.json').read_bytes();audit=json.loads(audit_bytes)
    targets=[c for c in json.loads(checked(base/'fixture-history-audit-v1/nominal_candidates.json',audit['artifacts']['nominal_candidates.json'])) if (c['season'],c['gw']) in TARGETS]
    if len(targets)!=len(TARGETS):raise ValueError('target population differs')
    observed=[];diagnostics=[];summary=[]
    for target in targets:
        p=previous(rows,target)
        if p is None:
            summary.append(dict(season=target['season'],gw=target['gw'],status='no_previously_selected_public_calendar'));continue
        old=json.loads(gzip.decompress(checked(base/p['object_root']/'objects'/p['normalized_sha256'],p['normalized_sha256'])))
        later=json.loads(gzip.decompress(checked(base/'fixture-history-audit-v1/objects'/target['normalized_sha256'],target['normalized_sha256'])))
        if len(old)!=380 or len(later)!=380:raise ValueError('expected full fixture identity population')
        delta=differences(old,later,target['deadline'])
        age=(aware(target['deadline'])-aware(p['source_committer_at'])).total_seconds()/3600
        entry=dict(season=target['season'],gw=target['gw'],deadline=target['deadline'],origin_gw=p['gw'],
            source_committer_at=p['source_committer_at'],available_at=p['available_at'],proof=p['proof'],
            nominal_commit_age_hours=age,normalized_sha256=p['normalized_sha256'],object_root=p['object_root'],
            older_calendar=old,training_admitted=False)
        observed.append(entry)
        impacts=horizon_changes(old,later,target['gw'])
        diagnostics.append(dict(season=target['season'],gw=target['gw'],later_unproven_sha256=target['normalized_sha256'],
            field_changes=delta,six_GW_club_count_changes=impacts,feature_admitted=False))
        summary.append(dict(season=target['season'],gw=target['gw'],status='older_published_calendar_only',origin_gw=p['gw'],
            nominal_commit_age_hours=age,available_at=p['available_at'],calendar_fixtures=len(old),
            fields_different=len(delta),fixtures_different=len({d['fixture'] for d in delta}),
            future_or_unknown_fields_different=sum(d['future_or_unknown'] for d in delta),
            event_fields_different=sum(d['field']=='event' for d in delta),six_GW_club_count_changes=len(impacts),
            older_unassigned_fixtures=sum(f['event'] is None for f in old),
            age_passes={str(days):age<=days*24 for days in (14,21,28)}))
    artifacts={}
    for name,data in [('older_observed_calendars.json',observed),('later_reference_diagnostics.json',diagnostics)]:
        payload=(json.dumps(data,indent=2)+'\n').encode();(out/name).write_bytes(payload);artifacts[name]=digest(payload)
    result=dict(version='calendar-staleness-audit-v1',parent_report_sha256=digest(report_bytes),fixture_audit_sha256=digest(audit_bytes),
        implementation_sha256=digest(Path(__file__).read_bytes()),targets=len(targets),older_published_calendars=len(observed),summary=summary,
        selected_calendar_coverage_unchanged='195/199',training_admitted=False,production_changed=False,new_FPL_labels=0,
        limitations=['availability_and_freshness_are_different_measurements',
            'age_is_Git_commit_age_not_API_capture_age',
            'later_unproven_snapshot_is_diagnostic_not_predeadline_ground_truth',
            'horizon_counts_describe_snapshot_schedules_not_realized_matches',
            'age_sensitivity_does_not_change_existing_selection_or_admission_thresholds',
            'no_previous_selected_calendar_does_not_prove_no_public_source_exists'],artifacts=artifacts)
    (out/'report.json').write_text(json.dumps(result,indent=2)+'\n');return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base-root',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.base_root,a.out),indent=2))


if __name__=='__main__':main()
