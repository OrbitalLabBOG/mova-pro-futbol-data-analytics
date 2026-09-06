"""Audit snapshot identity links to retrospective GT without admitting features."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked, verify


def link(snapshot, labels):
    mapping=labels[['element','official_player_code']].drop_duplicates()
    if mapping.isna().any().any() or mapping.element.duplicated().any() or mapping.official_player_code.duplicated().any():
        raise ValueError('ambiguous GT identity map')
    by_id=mapping.set_index('element').official_player_code.to_dict()
    by_code=mapping.set_index('official_player_code').element.to_dict()
    frame=pd.DataFrame(snapshot)[['id','code']].copy()
    duplicated=frame.id.duplicated(keep=False)|frame.code.duplicated(keep=False)
    statuses=[]; targets=[]
    for index,row in frame.iterrows():
        target=by_code.get(row.code)
        if duplicated.loc[index] or pd.isna(row.id) or pd.isna(row.code):
            status='invalid_or_duplicate_snapshot_identity'
        elif row.code not in by_code:
            status='code_absent_from_gt_with_id_conflict' if row.id in by_id else 'code_absent_from_gt'
        elif row.id != target:
            status='season_id_code_conflict'
        else:
            status='exact_season_id_and_code'
        statuses.append(status);targets.append(target if status=='exact_season_id_and_code' else None)
    frame['identity_status']=statuses
    frame['gt_element']=pd.array(targets,dtype='Int64')
    return frame


def build(base, out):
    spec=json.loads(Path(__file__).with_name('results-g84.json').read_text())
    root=base/'azure-history-g84'; coverage=base/'azure-coverage-g84-v1'
    capture=json.loads(checked(root/'report.json',spec['capture_report_sha256']))
    checked(root/'manifest.json',capture['manifest_sha256'])
    parent=json.loads(checked(coverage/'report.json',spec['coverage_report_sha256']))
    windows=json.loads(checked(coverage/'nominal_windows.json',parent['artifacts']['nominal_windows.json']))
    pointer_bytes=Path(__file__).with_name('current-labels.json').read_bytes();pointer=json.loads(pointer_bytes)
    package=base/'training-datasets'/pointer['dataset_id']
    checked(package/'manifest.json',pointer['manifest_sha256']);gt=verify(package)
    if gt['dataset_id'] != pointer['dataset_id']:raise ValueError('GT pointer mismatch')
    labels={entry['season']:pd.read_csv(package/entry['file'],compression='gzip') for entry in gt['partitions'] if entry['season'] in ('2020-21','2021-22')}
    observations=[]; missing=[]; summaries=[]; covered={s:set() for s in labels}; populations={s:set() for s in labels}
    for window in windows:
        season=window['season'];gw=window['gameweek'];f=labels[season]
        source=json.loads(checked(root/'objects'/window['source_sha256'],window['source_sha256']))
        if not any(e['id']==gw and pd.Timestamp(e['deadline_time'])==pd.Timestamp(window['deadline']) for e in source['events']):
            raise ValueError('deadline not declared in source')
        linked=link(source['elements'],f)
        matched=linked.loc[linked.identity_status.eq('exact_season_id_and_code'),'gt_element']
        target=f.loc[f.gw.eq(gw)]
        absent=target.loc[~target.element.isin(matched)].copy()
        common=dict(season=season,gameweek=gw,deadline=window['deadline'],source_sha256=window['source_sha256'],
                    available_at=None,eligible_predeadline=False,eligible_training=False)
        for key,value in common.items():linked[key]=value
        observations.append(linked)
        for key,value in common.items():absent[key]=value
        missing.append(absent[['season','gameweek','deadline','source_sha256','element','official_player_code','fixture','minutes','total_points','available_at','eligible_predeadline','eligible_training']])
        for row in target.itertuples():
            key=(int(row.element),int(row.fixture),int(row.gw));populations[season].add(key)
            if row.element in set(matched):covered[season].add(key)
        summaries.append(dict(**common,snapshot_players=len(linked),identity_status=linked.identity_status.value_counts().to_dict(),
                              gt_rows=len(target),gt_rows_without_exact_snapshot_identity=len(absent),
                              positive_minute_gt_rows_without_exact_snapshot_identity=int(absent.minutes.gt(0).sum()),
                              snapshot_players_without_gt_row_in_gw=int((~linked.gt_element.isin(target.element)).sum())))
    states=pd.concat(observations,ignore_index=True);absent=pd.concat(missing,ignore_index=True)
    seasons={}
    for season,f in labels.items():
        rows=states.loc[states.season.eq(season)];holes=absent.loc[absent.season.eq(season)]
        unique=holes.drop_duplicates(['element','fixture','gameweek'])
        seasons[season]=dict(window_variants=sum(w['season']==season for w in windows),
            state_window_rows=len(rows),identity_status=rows.identity_status.value_counts().to_dict(),
            gt_season_rows=len(f),unique_gt_rows_in_selected_gws=len(populations[season]),
            unique_gt_rows_with_exact_snapshot_identity=len(covered[season]),
            gt_row_window_comparisons_without_identity=len(holes),unique_gt_rows_missing_in_any_variant=len(unique),
            positive_minute_comparisons_without_identity=int(holes.minutes.gt(0).sum()),
            unique_positive_minute_gt_rows_missing_in_any_variant=int(unique.minutes.gt(0).sum()))
    out.mkdir(parents=True,exist_ok=True)
    states.to_csv(out/'state_identity_links.csv',index=False);absent.to_csv(out/'unmatched_gt_rows.csv',index=False)
    (out/'windows.json').write_text(json.dumps(summaries,indent=2,allow_nan=False)+'\n')
    report=dict(version='azure-gt-identity-v1',parent_coverage_sha256=spec['coverage_report_sha256'],
        gt_dataset_id=gt['dataset_id'],gt_pointer_sha256=digest(pointer_bytes),implementation_sha256=digest(Path(__file__).read_bytes()),
        seasons=seasons,artifacts={n:digest((out/n).read_bytes()) for n in ('state_identity_links.csv','unmatched_gt_rows.csv','windows.json')},
        training_admitted=False,production_changed=False,
        limitations=['identity_audit_not_predeadline_availability_proof','both_season_id_and_official_code_required_no_name_fallback',
                     'missing_gt_row_in_state_not_imputed_as_zero','GT_GW_is_retrospective_not_schedule_forecast',
                     'window_variants_are_repeated_comparisons_not_independent_examples',
                     'missing_in_any_variant_may_be_covered_in_another_variant'])
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.base,a.out),indent=2))
