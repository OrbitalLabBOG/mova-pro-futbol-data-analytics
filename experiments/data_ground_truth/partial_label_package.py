"""Version observed partial historical labels separately from unknowns and inference."""
from __future__ import annotations
import argparse
import io
import json
from pathlib import Path
import tempfile
import pandas as pd
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.raw_bundle import canonical,safe
from experiments.data_ground_truth.training_dataset import checked


def consolidate(frame):
    f=frame.copy();right=f.source_presence.eq('right_only');both=f.source_presence.eq('both')
    if not f.source_presence.isin(['left_only','right_only','both']).all():raise ValueError('unknown source presence')
    if (both&(f.fpl_id.ne(f.id)|f.gameweek.ne(f.gw))).any():raise ValueError('source identity or gameweek conflict')
    for old,new in [('minutes','mins'),('total','gw_pts')]:
        if (both&f[old].notna()&f[new].notna()&f[old].ne(f[new])).any():raise ValueError('conflicting observed values')
    recover=f.candidate_missing_points
    if (recover&(~both|~f.corroborated_link|f.total.notna()|f.gw_pts.isna())).any():raise ValueError('unsupported recovery')
    out=pd.DataFrame(dict(season='2013-14',element=f.fpl_id.where(~right,f.id),fixture=f.matchId,
        gw=f.gameweek.where(~right,f.gw),minutes=f.minutes.where(~right,f.mins),
        total_points=f.total.where(~recover,f.gw_pts).where(~right,f.gw_pts)))
    for col in ['element','fixture','gw']:
        if out[col].isna().any() or out[col].mod(1).ne(0).any():raise ValueError('invalid row identity')
        out[col]=out[col].astype('int64')
    if out.duplicated(['season','element','fixture']).any():raise ValueError('duplicate label identity')
    if not out.gw.between(1,38).all():raise ValueError('invalid gameweek')
    if (out.minutes.notna()&(~out.minutes.between(0,90)|out.minutes.mod(1).ne(0))).any():raise ValueError('invalid minutes')
    if (out.total_points.notna()&out.total_points.mod(1).ne(0)).any():raise ValueError('invalid points')
    out['minutes_source']='differential';out.loc[right,'minutes_source']='early_json'
    out['points_source']='differential';out.loc[right|recover,'points_source']='early_json'
    out.loc[out.minutes.isna(),'minutes_source']='unknown';out.loc[out.total_points.isna(),'points_source']='unknown'
    out['source_presence']=f.source_presence;out['recovered_from_json']=recover
    out['differential_player_id']=f.player_player_id;out['differential_fixture_id']=f.fixture_id;out['json_player_id']=f.id
    out['fixture_namespace']='pl_archive_events';out['player_namespace']='fpl_2013_14'
    out['label_status']=(out.minutes.notna()&out.total_points.notna()).map({True:'observed',False:'unknown'})
    out['eligible_training']=False;out['eligible_predeadline']=False
    return out.sort_values(['fixture','element']).reset_index(drop=True)


def verify(package):
    raw=(package/'manifest.json').read_bytes();manifest=json.loads(raw);payload={k:v for k,v in manifest.items() if k!='dataset_id'}
    if digest(canonical(payload))!=manifest['dataset_id'] or package.name!=manifest['dataset_id']:raise ValueError('partial dataset identity mismatch')
    tables={}
    expected={'observed_labels.csv','unknown_rows.csv','inferred_candidates.json'}
    if set(manifest['artifacts'])!=expected:raise ValueError('unexpected partial artifacts')
    for name,entry in manifest['artifacts'].items():
        safe(name);data=checked(package/name,entry['sha256'])
        if len(data)!=entry['bytes']:raise ValueError('partial artifact size mismatch')
        if name.endswith('.csv'):tables[name]=pd.read_csv(io.BytesIO(data))
    observed=tables['observed_labels.csv'];unknown=tables['unknown_rows.csv'];all_rows=pd.concat([observed,unknown],ignore_index=True)
    if all_rows.duplicated(['season','element','fixture']).any():raise ValueError('duplicate packaged identity')
    if observed[['minutes','total_points']].isna().any().any() or observed.label_status.ne('observed').any():raise ValueError('unknown values in observed labels')
    if not unknown[['minutes','total_points']].isna().any(axis=1).all() or unknown.label_status.ne('unknown').any():raise ValueError('observed values in unknown partition')
    if all_rows.eligible_training.any() or all_rows.eligible_predeadline.any():raise ValueError('unexpected partial admission')
    counts=dict(observed_rows=len(observed),unknown_rows=len(unknown),union_rows=len(all_rows),
        positive_minute_observed_rows=int(observed.minutes.gt(0).sum()),explicit_zero_minute_rows=int(observed.minutes.eq(0).sum()),
        observed_fixtures=int(observed.fixture.nunique()),observed_gameweeks=int(observed.gw.nunique()))
    if counts!=manifest['coverage']:raise ValueError('partial coverage mismatch')
    return manifest


def build(base,out):
    here=Path(__file__).parent;inputs={};reports={}
    for gate,dirname in [(89,'early-history-overlap-g89-v2'),(93,'annual-residual-evidence-g93-v1')]:
        reference=json.loads((here/f'results-g{gate}.json').read_text());root=base/dirname
        raw=checked(root/'report.json',reference['audit_report_sha256']);reports[gate]=(root,json.loads(raw));inputs[f'g{gate}_report_sha256']=digest(raw)
    root,r=reports[89];source=checked(root/'observations.csv',r['artifacts']['observations.csv']);inputs['g89_observations_sha256']=digest(source)
    rows=consolidate(pd.read_csv(io.BytesIO(source)));observed=rows.loc[rows.label_status.eq('observed')];unknown=rows.loc[rows.label_status.eq('unknown')]
    root,r=reports[93];inferences=checked(root/'annual_residual_cases.json',r['artifacts']['annual_residual_cases.json'])
    inputs['g93_inference_sha256']=digest(inferences)
    output={'observed_labels.csv':observed.to_csv(index=False).encode(),'unknown_rows.csv':unknown.to_csv(index=False).encode(),'inferred_candidates.json':inferences}
    descriptor=dict(version='partial-fpl-labels-v1',season='2013-14',sources=inputs,
        source_database_sha256=reports[89][1]['database_sha256'],source_json_sha256='21c74e98562268738a7b520b0518e6a48068f0b3117dc0c2e33660016f4f515e',
        implementation_sha256=digest(Path(__file__).read_bytes()),
        coverage=dict(observed_rows=len(observed),unknown_rows=len(unknown),union_rows=len(rows),
            positive_minute_observed_rows=int(observed.minutes.gt(0).sum()),explicit_zero_minute_rows=int(observed.minutes.eq(0).sum()),
            observed_fixtures=int(observed.fixture.nunique()),observed_gameweeks=int(observed.gw.nunique())),
        recovered_observed_points=int(observed.recovered_from_json.sum()),new_complete_seasons=0,training_admitted=False,
        limitations=['partial_registered_population_not_full_season_replay','season_scoped_ids_not_global_player_identity',
            'inferred_candidates_never_enter_observed_labels','retrospective_labels_not_predeadline_features','raw_source_values_preserved_in_parent_artifacts'],
        artifacts={n:dict(sha256=digest(data),bytes=len(data)) for n,data in output.items()})
    dataset_id=digest(canonical(descriptor));manifest=descriptor|dict(dataset_id=dataset_id);out.mkdir(parents=True,exist_ok=True);target=out/dataset_id
    if target.exists():verify(target);return target
    with tempfile.TemporaryDirectory(prefix='.partial-',dir=out) as tmp:
        stage=Path(tmp)/dataset_id;stage.mkdir()
        for n,data in output.items():(stage/n).write_bytes(data)
        (stage/'manifest.json').write_bytes(canonical(manifest));verify(stage);stage.rename(target)
    return target

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();print(build(a.base,a.out))
