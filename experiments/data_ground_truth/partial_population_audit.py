"""Measure partial observation sampling without inventing eligibility denominators."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import pandas as pd
from experiments.data_ground_truth.partial_label_package import verify
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked


def summarize(group):
    known=group.minutes.notna();positive=group.minutes.gt(0);zero=group.minutes.eq(0)
    both=known&group.total_points.notna()
    return dict(archived_rows=len(group),known_minute_rows=int(known.sum()),positive_minute_rows=int(positive.sum()),
        explicit_zero_minute_rows=int(zero.sum()),unknown_minute_rows=int((~known).sum()),
        observed_point_and_minute_rows=int(both.sum()),known_minutes_missing_points=int((known&group.total_points.isna()).sum()),
        positive_share_among_known_minutes=float(positive.sum()/known.sum()) if known.any() else None,
        registered_player_denominator=None,eligibility_population_proven=False,
        sampling_status='no_known_minutes' if not known.any() else 'positive_only_observations' if not zero.any() else 'mixed_observed_outcomes_population_unknown',
        participation_training_admitted=False)


def audit(frame):
    if frame.duplicated(['season','element','fixture']).any():raise ValueError('duplicate observation identity')
    if set(frame.season)!={'2013-14'} or not frame.gw.between(1,38).all():raise ValueError('unexpected season or gameweek')
    if frame.groupby('fixture').gw.nunique().gt(1).any():raise ValueError('fixture assigned to multiple gameweeks')
    fixtures=pd.DataFrame([dict(gw=int(gw),fixture=int(fixture),**summarize(g)) for (gw,fixture),g in frame.groupby(['gw','fixture'])])
    weeks=pd.DataFrame([dict(gw=int(gw),fixtures=int(g.fixture.nunique()),**summarize(g)) for gw,g in frame.groupby('gw')])
    phases={name:summarize(g) for name,g in [('GW1_30',frame.loc[frame.gw.le(30)]),('GW31_38',frame.loc[frame.gw.ge(31)])]}
    report=dict(version='partial-population-audit-v1',season='2013-14',phases=phases,
        positive_only_gameweeks=weeks.loc[weeks.sampling_status.eq('positive_only_observations'),'gw'].tolist(),
        fixtures_with_explicit_zero_minutes=int(fixtures.explicit_zero_minute_rows.gt(0).sum()),
        fixtures_with_only_positive_known_minutes=int(fixtures.sampling_status.eq('positive_only_observations').sum()),
        unknown_minutes_by_gameweek={str(int(r.gw)):int(r.unknown_minute_rows) for r in weeks.itertuples() if r.unknown_minute_rows},
        missing_points_with_known_minutes_by_gameweek={str(int(r.gw)):int(r.known_minutes_missing_points) for r in weeks.itertuples() if r.known_minutes_missing_points},
        new_labels=0,participation_training_admitted=False,production_changed=False,
        limitations=['observed_positive_share_not_probability_of_playing','no_eligibility_population_proof_even_in_mixed_windows',
                     'unknown_minutes_are_not_zero','missing_points_do_not_erase_known_minutes',
                     'conditional_on_play_analysis_does_not_prove_unconditional_training_validity'])
    return fixtures,weeks,report


def build(base,out):
    p=json.loads(Path(__file__).with_name('current-partial-labels.json').read_text());root=base/'partial-label-datasets'/p['dataset_id']
    checked(root/'manifest.json',p['manifest_sha256']);manifest=verify(root)
    frame=pd.concat([pd.read_csv(root/n) for n in ['observed_labels.csv','unknown_rows.csv']],ignore_index=True)
    fixtures,weeks,report=audit(frame);out.mkdir(parents=True,exist_ok=True)
    for n,df in [('fixture_windows.csv',fixtures),('gameweek_windows.csv',weeks)]:df.to_csv(out/n,index=False)
    report.update(partial_dataset_id=manifest['dataset_id'],partial_manifest_sha256=p['manifest_sha256'],implementation_sha256=digest(Path(__file__).read_bytes()),
        artifacts={n:digest((out/n).read_bytes()) for n in ['fixture_windows.csv','gameweek_windows.csv']})
    (out/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n');return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.base,a.out),indent=2))
