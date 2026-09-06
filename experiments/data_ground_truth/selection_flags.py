"""Measure raw selection flags separately from sporting status; never infer missing flags."""
from __future__ import annotations

import argparse
from collections import Counter
import gzip
import json
from pathlib import Path

from experiments.data_ground_truth.bootstrap_audit import decode, inspect
from experiments.data_ground_truth.bootstrap_time import aware
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked

FLAGS = ('can_select', 'can_transact', 'removed', 'has_temporary_code')
SELECTION_SHA = '1ace4506377f6bf92ff79d71f7b1083070f273c58f802518754f96fccb87b6fc'


def flag(element, field):
    if field not in element:
        return dict(kind='absent', value=None)
    value = element[field]
    if value is None:
        return dict(kind='null', value=None)
    if type(value) is not bool:
        return dict(kind='invalid_type', value=value)
    return dict(kind='boolean', value=value)


def observation(element):
    if element['status'] not in ('a', 'd', 'i', 'n', 's', 'u'):
        raise ValueError('unknown sporting status')
    fields = {f: flag(element, f) for f in FLAGS}
    select = fields['can_select']
    known = select['kind'] == 'boolean'
    return dict(status=element['status'], flags=fields,
                observed_selectability=select['value'] if known else None,
                status_a_filter_would_exclude_observed_selectable=known and select['value'] and element['status'] != 'a',
                status_u_rule_disagrees=known and select['value'] != (element['status'] != 'u'),
                transact_true_select_false=known and select['value'] is False and fields['can_transact'] == dict(kind='boolean', value=True),
                training_admitted=False)


def summarize(rows):
    flags = {f: Counter() for f in FLAGS}
    combinations = Counter()
    for r in rows:
        for f, cell in r['flags'].items():
            flags[f][str(cell['value']).lower() if cell['kind'] == 'boolean' else cell['kind']] += 1
        combinations[(r['status'], str(r['observed_selectability']).lower(),
                      r['flags']['can_select']['kind'])] += 1
    return dict(rows=len(rows), published_rows=sum(r['publication_bound'] is not None for r in rows),
                flags={f: dict(c) for f, c in flags.items()},
                combinations=[dict(status=k[0], observed_selectability=k[1], flag_kind=k[2], rows=v)
                              for k, v in sorted(combinations.items())],
                status_a_filter_exclusions=sum(r['status_a_filter_would_exclude_observed_selectable'] for r in rows),
                status_u_rule_disagreements=sum(r['status_u_rule_disagrees'] for r in rows),
                transact_true_select_false=sum(r['transact_true_select_false'] for r in rows))


def build(base: Path, out: Path):
    root = base / 'raw-bootstrap-snapshots'
    selection_root = base / 'publication-selection-v1'
    selection = json.loads(checked(selection_root / 'report.json', SELECTION_SHA))
    manifest = json.loads(checked(root / 'manifest.json', selection['manifest_sha256']))
    if manifest['errors'] or selection['errors'] or len(manifest['records']) != manifest['expected_files']:
        raise ValueError('incomplete source')
    targets = json.loads(checked(selection_root / 'nominal_deadline_candidates.json', selection['artifacts']['nominal_deadline_candidates.json']))
    proofs = json.loads(checked(selection_root / 'publication_witnesses.json', selection['artifacts']['publication_witnesses.json']))
    proof_map = {(p['season'], p['gw']): p for p in proofs}
    if len(proof_map) != len(proofs):
        raise ValueError('duplicate proof')
    records = {r['path']: r for r in manifest['records']}
    rows = []; windows = []; seen = set()
    for c in targets:
        key = (c['season'], c['gw'])
        if key in seen or records[c['path']]['sha256'] != c['sha256']:
            raise ValueError('duplicate target or source mismatch')
        seen.add(key)
        p = proof_map.get(key)
        if p and (p['source_sha256'] != c['sha256'] or p['deadline'] != c['deadline'] or
                  p['eligible_predeadline'] is not True or not aware(p['available_at']) < aware(c['deadline'])):
            raise ValueError('invalid publication binding')
        snapshot = decode(checked(root / 'objects' / c['sha256'], c['sha256']))
        _, observed = inspect(snapshot, c['path'])
        if not any(all(x[f] == c[f] for f in ('season', 'gw', 'deadline', 'source_claimed_at')) for x in observed):
            raise ValueError('snapshot calendar mismatch')
        group = []; ids = set()
        for e in snapshot['elements']:
            if type(e['id']) is not int or e['id'] <= 0 or e['id'] in ids or e['element_type'] not in (1, 2, 3, 4, 5):
                raise ValueError('invalid or duplicate entity')
            ids.add(e['id'])
            group.append(dict(season=c['season'], gw=c['gw'], element=e['id'], source_code=e['code'],
                              entity_type='manager' if e['element_type'] == 5 else 'player',
                              source_sha256=c['sha256'], deadline=c['deadline'],
                              publication_bound=p['available_at'] if p else None, **observation(e)))
        rows.extend(group)
        windows.append(dict(season=c['season'], gw=c['gw'],
                            players=summarize([r for r in group if r['entity_type'] == 'player']),
                            managers=summarize([r for r in group if r['entity_type'] == 'manager'])))
    if not proof_map.keys() <= seen:
        raise ValueError('proof outside target universe')
    players = [r for r in rows if r['entity_type'] == 'player']
    seasons = {s: summarize([r for r in players if r['season'] == s]) for s in sorted({r['season'] for r in players})}
    payload = gzip.compress(('\n'.join(json.dumps(r, sort_keys=True) for r in rows) + '\n').encode(), mtime=0)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'observations.jsonl.gz').write_bytes(payload)
    report = dict(version='raw-selection-flags-v1', selection_report_sha256=SELECTION_SHA,
                  raw_manifest_sha256=selection['manifest_sha256'], implementation_sha256=digest(Path(__file__).read_bytes()),
                  observations_sha256=digest(payload), players=summarize(players),
                  managers=summarize([r for r in rows if r['entity_type'] == 'manager']),
                  seasons=seasons, windows=windows, training_admitted=False, production_changed=False,
                  limitations=['observed_flags_not_verified_server_transaction_permissions',
                               'absence_null_and_invalid_are_unknown_not_false',
                               'concordance_with_status_u_does_not_authorize_historical_imputation',
                               'sporting_status_not_a_selection_permission',
                               'publication_proof_is_not_exact_API_capture_time',
                               'no_new_seasons_or_labels_no_retrospective_label_inputs'])
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base-root', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    print(json.dumps(build(args.base_root, args.out)['players'], indent=2))


if __name__ == '__main__':
    main()
