"""Trace rejected profile totals through neighboring archived snapshots."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked


def observe(players, element, code):
    player = players.get(str(element))
    if player is None:
        return dict(status='profile_absent')
    if player.get('id') != element or player.get('code') != code:
        return dict(status='identity_mismatch')
    rows = player['fixture_history']['all']
    if any(len(row) != 20 for row in rows):
        raise ValueError('invalid history width')
    values = [player['total_points']] + [row[-1] for row in rows]
    if any(isinstance(v, bool) or not isinstance(v, int) for v in values):
        raise ValueError('nonintegral source points')
    total = sum(row[-1] for row in rows)
    return dict(status='consistent' if total == player['total_points'] else 'total_mismatch',
                source_name=player.get('web_name'), profile_total=player['total_points'],
                history_total=total, history_minus_profile=total-player['total_points'],
                history_rows=len(rows), last_history_row=rows[-1] if rows else None,
                history_sha256=digest(json.dumps(rows, sort_keys=True).encode()),
                final_observation_proven=False, eligible_training=False)


def build(base, out):
    directory = Path(__file__).parent
    g100 = json.loads((directory/'results-g100.json').read_text())
    g102 = json.loads((directory/'results-g102.json').read_text())
    inventory_sha = g100['audit']['artifacts']['snapshots.json']
    projection_sha = g102['audit']['artifacts']['projections.json']
    inventory = json.loads(checked(base/'profile-snapshot-audit-g100-v1/snapshots.json', inventory_sha))
    projections = json.loads(checked(base/'unscored-history-g102-v1/projections.json', projection_sha))
    entries = sorted((e for e in inventory if e['status'] == 'profile_history_schema_valid'), key=lambda e:e['nominal_filename_time'])
    positions = {e['path']:i for i,e in enumerate(entries)}
    selected = [p for p in projections if p['status']=='unmapped' and 'profile total mismatch' in p['errors'].values()]
    traces = []
    snapshots = {}
    for target in selected:
        index = positions[target['representative_path']]
        if entries[index]['sha256'] != target['representative_sha256']:
            raise ValueError('target identity mismatch')
        neighbors = entries[max(0,index-1):index+2]
        payloads = {}
        for entry in neighbors:
            data = checked(base/'profile-snapshots-g100/objects'/entry['sha256'], entry['sha256'])
            payloads[entry['path']] = json.loads(data)
            snapshots[entry['path']] = entry['sha256']
        players = payloads[target['representative_path']]
        for player in players.values():
            element, code = player['id'], player['code']
            state = observe(players, element, code)
            if state['status'] != 'total_mismatch':
                continue
            observations = []
            for entry in neighbors:
                role = 'target' if entry['path']==target['representative_path'] else ('previous' if entry['nominal_filename_time'] < entries[index]['nominal_filename_time'] else 'next')
                observations.append({k:entry[k] for k in ('path','sha256','nominal_filename_time')} |
                    dict(role=role) | observe(payloads[entry['path']], element, code))
            traces.append(dict(element=element, code=code, target_path=target['representative_path'], observations=observations))
    out.mkdir(parents=True, exist_ok=True)
    (out/'traces.json').write_text(json.dumps(traces, indent=2)+'\n')
    report = dict(version='profile-total-consistency-v1', implementation_sha256=digest(Path(__file__).read_bytes()),
        source_inventory_sha256=inventory_sha, source_projections_sha256=projection_sha,
        target_snapshots=len(selected), inspected_snapshots=len(snapshots), inconsistent_profiles=len(traces),
        consistent_previous=sum(any(o['role']=='previous' and o['status']=='consistent' for o in t['observations']) for t in traces),
        consistent_next=sum(any(o['role']=='next' and o['status']=='consistent' for o in t['observations']) for t in traces),
        neighbor_identity_mismatches=sum(o['status']=='identity_mismatch' for t in traces for o in t['observations']),
        finalized_labels_admitted=0, gt_changed=False, production_changed=False,
        limitations=['four_rejected_representatives_not_full_collection_total_audit',
            'nominal_filename_order_not_publication_proof', 'adjacent_valid_schema_snapshots_only',
            'consistent_totals_do_not_prove_finalization', 'neighbors_do_not_authorize_source_repair',
            'no_cause_or_atomicity_inferred'],
        artifacts={'traces.json':digest((out/'traces.json').read_bytes())})
    (out/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.base, args.out), indent=2))
