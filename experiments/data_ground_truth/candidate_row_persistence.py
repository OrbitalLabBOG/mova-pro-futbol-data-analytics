"""Trace candidate zeros across archived profiles; disappearance is not eligibility proof."""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked

CASES=[dict(element=84,code=126184,fixture=803174,gw=2,date='16 Aug 16:00',opponent='MCI(A)'),
       dict(element=201,code=77454,fixture=803201,gw=4,date='29 Aug 15:00',opponent='WHU(H)'),
       dict(element=231,code=37642,fixture=803196,gw=4,date='30 Aug 16:00',opponent='SWA(A)')]


def observe(players,case):
    player=players.get(str(case['element']))
    if player is None:return dict(status='profile_absent',candidate_row=None)
    if player.get('id')!=case['element'] or player.get('code')!=case['code']:
        return dict(status='identity_mismatch',candidate_row=None)
    history=player['fixture_history']['all']
    rows=[r for r in history if r[0]==case['date'] and r[1]==case['gw'] and r[2].startswith(case['opponent']+' ')]
    if len(rows)>1:raise ValueError('ambiguous candidate history row')
    return dict(status='row_present' if rows else 'row_absent',candidate_row=rows[0] if rows else None,
        source_name=player['web_name'],source_team_name=player['team_name'],source_team_code=player['team_code'],
        source_status=player['status'],same_gameweek_rows=[r for r in history if r[1]==case['gw']],
        final_observation_proven=False,eligible_training=False)


def summarize(observations):
    present=[r for r in observations if r['status']=='row_present'];transitions=[];prior=None
    for r in observations:
        state=(r['status'],r.get('source_team_code'))
        if state!=prior:
            transitions.append({k:r.get(k) for k in ['path','sha256','nominal_filename_time','status','source_team_name','source_team_code','candidate_row','same_gameweek_rows']});prior=state
    return dict(snapshots=len(observations),statuses=dict(Counter(r['status'] for r in observations)),
        candidate_rows_with_nonzero_minutes_or_points=sum(r['candidate_row'][3]!=0 or r['candidate_row'][-1]!=0 for r in present),
        first_nominal_row_presence=present[0]['nominal_filename_time'] if present else None,
        last_nominal_row_presence=present[-1]['nominal_filename_time'] if present else None,
        last_snapshot_status=observations[-1]['status'] if observations else None,
        transitions=transitions,final_observation_proven=False,eligible_training=False)


def build(base,out):
    g100=json.loads(Path(__file__).with_name('results-g100.json').read_text());root=base/'profile-snapshot-audit-g100-v1'
    entries=json.loads(checked(root/'snapshots.json',g100['audit']['artifacts']['snapshots.json']))
    # Nominal filename range selects an archive slice, not a publication assertion.
    selected=sorted([e for e in entries if e['status']=='profile_history_schema_valid' and '2015-07'<=e['nominal_filename_time']<'2016'],key=lambda e:e['path'])
    traces={str(c['element']):[] for c in CASES}
    for i,e in enumerate(selected,1):
        data=checked(base/'profile-snapshots-g100/objects'/e['sha256'],e['sha256']);players=json.loads(data)
        for case in CASES:
            traces[str(case['element'])].append({k:e[k] for k in ['path','sha256','nominal_filename_time']}|observe(players,case))
        if i%200==0:print(f'traced {i}/{len(selected)} snapshots',flush=True)
    out.mkdir(parents=True,exist_ok=True)
    (out/'traces.json').write_text(json.dumps(traces,indent=2)+'\n')
    report=dict(version='candidate-row-persistence-v1',source_inventory_sha256=g100['audit']['artifacts']['snapshots.json'],
        implementation_sha256=digest(Path(__file__).read_bytes()),snapshots=len(selected),bytes=sum(e['bytes'] for e in selected),
        cases=[case|summarize(traces[str(case['element'])]) for case in CASES],
        finalized_labels_admitted=0,gt_changed=False,production_changed=False,
        limitations=['nominal_filename_order_not_publication_proof','profile_team_changes_not_transfer_eligibility_proof',
                    'row_disappearance_not_proof_of_zero_or_nonregistration','invalid_json_snapshots_excluded_by_G100_inventory',
                    'source_state_is_not_independent_final_result_evidence'],
        artifacts={'traces.json':digest((out/'traces.json').read_bytes())})
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.base,a.out),indent=2))
