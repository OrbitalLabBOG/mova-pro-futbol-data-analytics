"""Bracket first observed identities; never infer exact registration time."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd

from experiments.data_ground_truth.azure_coverage import named_time
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked


def reference(record):
    return dict(source_sha256=record['sha256'], url=record['url'],
                nominal_time=named_time(record['listing_item']['name']).isoformat(),
                available_at=None, eligible_predeadline=False)


def scan(records, targets, read_object):
    histories={key:dict(first_native=None,last_without_native=None,first_exact=None,last_without_exact=None) for key in targets}
    previous={}; excluded=[]
    for record in sorted(records,key=lambda r:(r['content_summary']['season'],r['listing_item']['name'])):
        season=record['content_summary']['season'];data=json.loads(read_object(record['sha256']))
        timestamp=named_time(record['listing_item']['name'])
        try:
            declared=datetime.fromisoformat(data.get('download_time'))
            delta=abs((declared.replace(tzinfo=None)-timestamp.replace(tzinfo=None)).total_seconds())
        except (ValueError,TypeError):delta=None
        if delta is None or delta>60:
            excluded.append(reference(record));continue
        players={p['id']:p for p in data['elements']}
        if len(players)!=len(data['elements']):raise ValueError('duplicate native ID')
        current=reference(record)
        for key,history in histories.items():
            s,element,code=key
            if s!=season:continue
            player=players.get(element)
            if player is not None and history['first_native'] is None:
                history['first_native']=dict(current,observed_code=player['code'])
                history['last_without_native']=previous.get(season)
            if player is not None and player['code']==code and history['first_exact'] is None:
                history['first_exact']=dict(current,observed_code=player['code'])
                history['last_without_exact']=previous.get(season)
        previous[season]=current
    return histories,excluded


def classification(history, deadline, kind):
    first=history['first_'+kind];previous=history['last_without_'+kind]
    if first is None:return 'not_observed_in_archive'
    deadline=datetime.fromisoformat(deadline)
    if datetime.fromisoformat(first['nominal_time'])<deadline:return 'first_observed_before_deadline'
    if previous is None:return 'first_observed_at_or_after_deadline_without_lower_bound'
    if datetime.fromisoformat(previous['nominal_time'])>=deadline:return 'absent_in_snapshot_at_or_after_deadline'
    return 'observation_interval_straddles_deadline'


def build(base,out):
    spec=json.loads(Path(__file__).with_name('results-g85.json').read_text())
    parent_root=base/'azure-gt-identity-g85-v1'
    parent=json.loads(checked(parent_root/'report.json',spec['audit_report_sha256']))
    holes=pd.read_csv(parent_root/'unmatched_gt_rows.csv')
    checked(parent_root/'unmatched_gt_rows.csv',parent['artifacts']['unmatched_gt_rows.csv'])
    targets={(r.season,int(r.element),int(r.official_player_code)) for r in holes.itertuples()}
    spec84=json.loads(Path(__file__).with_name('results-g84.json').read_text());raw=base/'azure-history-g84'
    capture=json.loads(checked(raw/'report.json',spec84['capture_report_sha256']))
    manifest=json.loads(checked(raw/'manifest.json',capture['manifest_sha256']))
    histories,excluded=scan(manifest['records'],targets,lambda sha:checked(raw/'objects'/sha,sha))
    cases=[]; first_events={}
    for row in holes.itertuples():
        key=(row.season,int(row.element),int(row.official_player_code));history=histories[key]
        first=history['first_exact']
        first_deadline=None
        if first is not None:
            sha=first['source_sha256']
            if sha not in first_events:
                first_events[sha]=json.loads(checked(raw/'objects'/sha,sha))['events']
            first_deadline=next(e['deadline_time'] for e in first_events[sha] if e['id']==int(row.gameweek))
        cases.append(dict(season=row.season,element=int(row.element),official_player_code=int(row.official_player_code),
            fixture=int(row.fixture),gameweek=int(row.gameweek),deadline=row.deadline,source_sha256=row.source_sha256,
            minutes=int(row.minutes),total_points=int(row.total_points),
            first_exact_snapshot_declared_deadline=first_deadline,
            first_exact_snapshot_deadline_differs=(pd.Timestamp(first_deadline)!=pd.Timestamp(row.deadline)) if first_deadline else None,
            native_observation_class=classification(history,row.deadline,'native'),
            exact_observation_class=classification(history,row.deadline,'exact'),
            eligible_predeadline=False,eligible_training=False))
    serialized=[dict(season=s,element=e,official_player_code=c,**histories[(s,e,c)]) for s,e,c in sorted(histories)]
    out.mkdir(parents=True,exist_ok=True)
    for name,value in [('identity_observation_brackets.json',serialized),('window_cases.json',cases),('excluded_clocks.json',excluded)]:
        (out/name).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
    positive=[c for c in cases if c['minutes']>0]
    report=dict(version='azure-observation-brackets-v1',parent_report_sha256=spec['audit_report_sha256'],
        manifest_sha256=capture['manifest_sha256'],implementation_sha256=digest(Path(__file__).read_bytes()),
        snapshots_checked=len(manifest['records']),excluded_clock_snapshots=len(excluded),target_identities=len(targets),
        identities_with_native_observation=sum(h['first_native'] is not None for h in histories.values()),
        identities_with_exact_observation=sum(h['first_exact'] is not None for h in histories.values()),
        first_native_code_differs_from_gt=sum(h['first_native'] is not None and h['first_native']['observed_code']!=key[2] for key,h in histories.items()),
        window_cases=len(cases),positive_minute_cases=len(positive),
        native_classes=dict(Counter(c['native_observation_class'] for c in cases)),
        exact_classes=dict(Counter(c['exact_observation_class'] for c in cases)),
        positive_native_classes=dict(Counter(c['native_observation_class'] for c in positive)),
        positive_exact_classes=dict(Counter(c['exact_observation_class'] for c in positive)),
        positive_first_before_deadline_with_changed_deadline=sum(c['exact_observation_class']=='first_observed_before_deadline' and c['first_exact_snapshot_deadline_differs'] is True for c in positive),
        artifacts={n:digest((out/n).read_bytes()) for n in ('identity_observation_brackets.json','window_cases.json','excluded_clocks.json')},
        training_admitted=False,production_changed=False,
        limitations=['nominal_observation_brackets_not_registration_or_publication_times',
                     'absence_in_one_snapshot_not_continuous_absence_or_proof_of_ineligibility',
                     'first_native_observation_not_identity_correction_authorization',
                     'aligned_wall_clocks_do_not_prove_UTC_capture',
                     'postdeadline_evidence_is_diagnostic_only_not_a_feature'])
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.base,a.out),indent=2))
