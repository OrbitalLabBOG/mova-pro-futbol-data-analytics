"""Constrain missing historical points using annual totals, without GT imputation."""
from __future__ import annotations
import argparse
import io
import json
from pathlib import Path
import pandas as pd
from experiments.data_ground_truth.identity_2014 import name_tokens
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked

EARLY_SHA='21c74e98562268738a7b520b0518e6a48068f0b3117dc0c2e33660016f4f515e'
LATER_SHA='4ba748103b6ba6abf3e8c1e8701cee3bb733f74e5570e2977f2b546670774e36'


def residual(group,annual):
    # Recovered observations remain separate from raw Differential values.
    points=group.total.where(~group.candidate_missing_points,group.gw_pts)
    unknown=points.isna()
    result=dict(rows=len(group),unknown_point_rows=int(unknown.sum()),unknown_minute_rows=int(group.minutes.isna().sum()),
        observed_points_sum=float(points.sum()),observed_minutes_sum=float(group.minutes.sum()),
        json_observation_recoveries=int(group.candidate_missing_points.sum()),annual_minutes=None,annual_points=None,
        inferred_points=None,status='missing_annual_reference',eligible_training=False,observed_label=False)
    if annual is None:return result
    result.update(annual_minutes=annual[1],annual_points=annual[-1])
    if unknown.sum()!=1:result['status']='not_one_unknown_point_row'
    elif group.minutes.isna().any():result['status']='missing_minutes'
    elif group.minutes.lt(0).any() or group.minutes.sum()!=annual[1]:result['status']='annual_minutes_disagree'
    else:
        value=annual[-1]-points.sum()
        if pd.isna(value) or value%1:result['status']='invalid_point_residual'
        else:result.update(status='conditional_annual_residual',inferred_points=int(value))
    return result


def audit(frame,early,later):
    if len({p['id'] for p in early})!=len(early) or len({p['code'] for p in later})!=len(later):raise ValueError('ambiguous source identity')
    by_id={p['id']:p for p in early};by_code={p['code']:p for p in later};cases=[]
    old=frame.loc[frame.source_presence.ne('right_only')].copy()
    for pid,g in old.groupby('fpl_id'):
        pending=g.minutes.gt(0)&g.total.isna()&~g.candidate_missing_points
        if not pending.any():continue
        ep=by_id.get(int(pid));lp=by_code.get(ep['code']) if ep else None
        full=lambda p:name_tokens(p['first_name']+' '+p['second_name'])
        identity=bool(ep and lp and full(ep)==full(lp) and full(ep) and all(name_tokens(n)<=full(ep) for n in g.differential_name))
        histories=[h for h in lp.get('season_history',[]) if h[0]=='2013/14'] if identity else []
        if len(histories)>1:raise ValueError('ambiguous annual history')
        result=residual(g,histories[0] if histories else None)
        for row in g.loc[pending].itertuples():
            cases.append(result|dict(season='2013-14',season_fpl_id=int(pid),name=row.differential_name,
                fixture=int(row.matchId),gameweek=int(row.gameweek),raw_minutes=float(row.minutes),raw_points=None,
                source_code=ep['code'] if ep else None,identity_corroborated=identity,
                available_at=None,eligible_predeadline=False))
    return cases


def build(base,out):
    gate=json.loads(Path(__file__).with_name('results-g89.json').read_text())
    root=base/'early-history-overlap-g89-v2';rb=checked(root/'report.json',gate['audit_report_sha256']);prior=json.loads(rb)
    frame=pd.read_csv(io.BytesIO(checked(root/'observations.csv',prior['artifacts']['observations.csv'])))
    raw=base/'early-fpl-json-g88/objects'
    early=json.loads(checked(raw/EARLY_SHA,EARLY_SHA));later=json.loads(checked(raw/LATER_SHA,LATER_SHA))
    cases=audit(frame,early,later);out.mkdir(parents=True,exist_ok=True)
    (out/'annual_residual_cases.json').write_text(json.dumps(cases,indent=2,allow_nan=False)+'\n')
    report=dict(version='annual-residual-evidence-v1',g89_report_sha256=digest(rb),early_source_sha256=EARLY_SHA,later_source_sha256=LATER_SHA,
        implementation_sha256=digest(Path(__file__).read_bytes()),pending_positive_appearances=len(cases),
        conditional_residual_cases=sum(c['status']=='conditional_annual_residual' for c in cases),
        conditional_zero_cases=sum(c['inferred_points']==0 for c in cases),
        cases_without_annual_reference=sum(c['status']=='missing_annual_reference' for c in cases),
        independently_recovered_match_labels=0,remaining_unobserved_match_labels=len(cases),
        new_complete_seasons=0,training_admitted=False,production_changed=False,
        limitations=['annual_residual_is_inferred_not_observed_match_points','requires_complete_and_correct_annual_reference',
                     'minute_sum_agreement_does_not_prove_complete_registered_player_universe','no_blanket_NULL_to_zero_rule',
                     'annual_reference_and_match_archive_may_share_upstream_source'],
        artifacts={'annual_residual_cases.json':digest((out/'annual_residual_cases.json').read_bytes())})
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.base,a.out),indent=2))
