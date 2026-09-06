"""Compare a newly acquired historical profile archive without double-counting labels."""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
import re
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked


def compare_profile(prior,current):
    if prior['id']!=current['id'] or prior['code']!=current['code']:raise ValueError('profile identity mismatch')
    differences=sorted(k for k in prior.keys()|current.keys() if prior.get(k)!=current.get(k))
    old=prior['season_history'];new=current['season_history']
    appended=len(new)==len(old)+1 and new[:-1]==old
    last=new[-1] if appended else None
    return dict(player_id=current['id'],player_code=current['code'],changed_fields=differences,
        fixture_history_equal=prior['fixture_history']==current['fixture_history'],
        prior_annual_history_preserved=appended,appended_season=last[0] if last else None,
        appended_minutes_match_snapshot=bool(last and last[1]==current['minutes']),
        appended_points_match_snapshot=bool(last and last[-1]==current['total_points']),
        eligible_training=False,eligible_predeadline=False)


def build(base,out):
    root=base/'gaffer-source-g96';mb=(root/'manifest.json').read_bytes();records=json.loads(mb)['records']
    oldroot=base/'raw-history-2015';ob=(oldroot/'manifest.json').read_bytes();oldrecords=json.loads(ob)['records'];prior={}
    for r in oldrecords:
        if not r['path'].startswith('PlayersInfo/'):continue
        payload=checked(oldroot/'objects'/r['sha256'],r['sha256']);p=json.loads(payload)
        if p['code'] in prior:raise ValueError('duplicate baseline player code')
        prior[p['code']]=(p,r)
    tb=(base/'historical-discovery-g96/barryedmund--gaffer.json').read_bytes();tree=json.loads(tb)
    expected={x['path'] for x in tree['tree']['tree'] if x['type']=='blob' and re.fullmatch(r'public/player_data/2015_16_[0-9]+\.json',x['path'])}
    selected=[r for r in records if r['path'].startswith('public/player_data/')]
    if len(selected)!=len(expected) or {r['path'] for r in selected}!=expected:raise ValueError('incomplete or duplicate profile capture')
    evidence=[];fields=Counter();codes=set()
    for r in records:
        if r['repository']!=tree['repository'] or r['revision']!=tree['revision']:raise ValueError('source revision differs')
        payload=checked(root/'objects'/r['sha256'],r['sha256'])
        if len(payload)!=r['bytes']:raise ValueError('source size differs')
        if r not in selected:continue
        p=json.loads(payload);code=p['code']
        if code in codes or int(Path(r['path']).stem.split('_')[-1])!=code:raise ValueError('source player code conflict')
        codes.add(code)
        if code not in prior:raise ValueError('unmatched baseline player')
        old,oldr=prior[code];entry=compare_profile(old,p);fields.update(entry['changed_fields'])
        evidence.append(entry|dict(source_path=r['path'],source_sha256=r['sha256'],prior_path=oldr['path'],prior_sha256=oldr['sha256']))
    out.mkdir(parents=True,exist_ok=True);(out/'profile_comparisons.json').write_text(json.dumps(evidence,indent=2)+'\n')
    report=dict(version='gaffer-source-audit-v1',manifest_sha256=digest(mb),prior_manifest_sha256=digest(ob),tree_response_sha256=digest(tb),
        implementation_sha256=digest(Path(__file__).read_bytes()),repository=tree['repository'],revision=tree['revision'],
        captured_files=len(records),captured_bytes=sum(r['bytes'] for r in records),profiles=len(evidence),
        identical_fixture_histories=sum(r['fixture_history_equal'] for r in evidence),
        preserved_annual_prefixes=sum(r['prior_annual_history_preserved'] for r in evidence),
        appended_seasons=sorted({r['appended_season'] for r in evidence if r['appended_season']}),
        appended_minutes_matching_snapshot=sum(r['appended_minutes_match_snapshot'] for r in evidence),
        appended_points_matching_snapshot=sum(r['appended_points_match_snapshot'] for r in evidence),
        changed_field_profiles=dict(sorted(fields.items())),baseline_codes_without_source=len(set(prior)-codes),
        new_match_labels_vs_baseline=0 if all(r['fixture_history_equal'] for r in evidence) else None,
        training_admitted=False,production_changed=False,new_complete_seasons=0,
        limitations=['matching_archives_do_not_prove_source_independence','appended_annual_rows_not_new_match_labels',
                     'mutable_state_differences_not_predeadline_publication_proof','does_not_recover_2013_14_GW34_or_GW38'],
        artifacts={'profile_comparisons.json':digest((out/'profile_comparisons.json').read_bytes())})
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.base,a.out),indent=2))
