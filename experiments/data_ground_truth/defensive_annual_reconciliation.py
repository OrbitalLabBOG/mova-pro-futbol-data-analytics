"""Test a fixed defensive composition hypothesis, keeping provider differences."""
from __future__ import annotations

import argparse
from collections import Counter
import gzip
import json
from pathlib import Path

import pandas as pd

from experiments.data_ground_truth.bootstrap_audit import decode
from experiments.data_ground_truth.core_defensive_matches import FIELDS
from experiments.data_ground_truth.preseason_supplemental import code_key
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked

POSITION_SHA = 'eee31c9ece4864963bff4d88543ac5d440ca4d574ec89512e680d6e697f9a086'
ARTICLE_SHA = 'c523044cfd0651c596662f87526920cf60b0393a9d17c216d311ba8bfff1792d'


def composition(values, position, tackle_field='tackles'):
    if tackle_field not in ('tackles', 'tackles_won'):
        raise ValueError('unsupported tackle hypothesis')
    if position not in (2, 3, 4):
        return None
    fields = ['clearances', 'blocks', 'interceptions', tackle_field]
    if position in (3, 4):
        fields.append('recoveries')
    if any(values.get(f) is None for f in fields):
        return None
    if any(type(values[f]) is not int or values[f] < 0 for f in fields):
        raise ValueError('invalid nonnegative action count')
    return sum(values[f] for f in fields)


def compare_player(annual, actions, position):
    if annual['status'] != 'observed_value':
        return dict(status='annual_' + annual['status'])
    if actions is None:
        return dict(status='no_provider_appearance_reference')
    if position is None:
        return dict(status='no_position_in_2025_GW1')
    if position == 1:
        return dict(status='goalkeeper_out_of_scope')
    primary = composition(actions, position)
    sensitivity = composition(actions, position, 'tackles_won')
    if primary is None or sensitivity is None:
        return dict(status='incomplete_provider_components')
    reference = annual['value']
    return dict(status='compared', annual_value=reference, primary_value=primary,
                primary_delta=primary-reference, sensitivity_value=sensitivity,
                sensitivity_delta=sensitivity-reference)


def build(core_root, annual_root, bootstrap_root, evidence_root, out):
    parents = {}
    for name, root in [('core', core_root), ('annual', annual_root)]:
        raw = (root / 'report.json').read_bytes()
        report = json.loads(raw)
        # Every input artifact is checked, not only the one consumed below.
        for file, sha in report['artifacts'].items():
            checked(root / file, sha)
        parents[name] = dict(report=report, sha256=digest(raw))
    core = parents['core']['report']
    if core['season'] != '2024-25' or core['missing_positive_GT_appearances'] or core['unpaired_rows']:
        raise ValueError('incomplete provider appearance linkage')
    if parents['annual']['report']['season'] != '2024/25':
        raise ValueError('wrong annual reference period')
    checked(evidence_root / 'objects' / ARTICLE_SHA, ARTICLE_SHA)
    snapshot = decode(checked(bootstrap_root / 'objects' / POSITION_SHA, POSITION_SHA))
    positions = {}
    for element in snapshot['elements']:
        code = code_key(element['code'])
        if code in positions or type(element['element_type']) is not int or element['element_type'] not in (1, 2, 3, 4):
            raise ValueError('ambiguous or invalid snapshot position')
        positions[code] = element['element_type']
    frame = pd.read_csv(core_root / 'observations.csv', dtype={'official_player_code': str})
    if len(frame) != core['paired_rows'] or frame.duplicated(['fixture', 'official_player_code']).any():
        raise ValueError('provider keys/row count mismatch')
    for field in FIELDS:
        values = pd.to_numeric(frame[field], errors='raise')
        if values.isna().any() or not (values.ge(0) & values.mod(1).eq(0)).all():
            raise ValueError('incomplete or invalid provider action counts')
    sums = frame.groupby('official_player_code')[FIELDS].sum(min_count=1)
    totals = {code_key(code): {f: int(row[f]) for f in FIELDS} for code, row in sums.iterrows()}
    payload = (annual_root / 'annual-reference.jsonl.gz').read_bytes()
    annual_rows = [json.loads(line) for line in gzip.decompress(payload).splitlines()]
    codes = [code_key(row['source_code']) for row in annual_rows]
    if len(codes) != len(set(codes)):
        raise ValueError('duplicate annual code')
    output = []
    for row in annual_rows:
        if row['season'] != '2024/25':
            raise ValueError('mixed annual periods')
        code = code_key(row['source_code'])
        position = positions.get(code)
        output.append(dict(source_code=code, season='2024/25', position_2025_GW1=position,
            provider_action_totals=totals.get(code), **compare_player(
                row['cells']['defensive_contribution'], totals.get(code), position)))
    compared = [r for r in output if r['status'] == 'compared']
    out.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(output, indent=2) + '\n').encode()
    (out / 'comparisons.json').write_bytes(data)
    result = dict(version='defensive-annual-reconciliation-v1', rows=len(output),
        core_report_sha256=parents['core']['sha256'], annual_report_sha256=parents['annual']['sha256'],
        position_snapshot_sha256=POSITION_SHA, documentary_article_sha256=ARTICLE_SHA,
        implementation_sha256=digest(Path(__file__).read_bytes()), statuses=dict(Counter(r['status'] for r in output)),
        primary=dict(formula='CBIT_DEF_CBIRT_MID_FWD_using_tackles', equal=sum(r['primary_delta']==0 for r in compared),
                     different=sum(r['primary_delta']!=0 for r in compared)),
        sensitivity=dict(formula='same_roles_using_tackles_won', equal=sum(r['sensitivity_delta']==0 for r in compared),
                         different=sum(r['sensitivity_delta']!=0 for r in compared)),
        positions={str(p): dict(rows=sum(r['position_2025_GW1']==p for r in compared),
                    primary_equal=sum(r['position_2025_GW1']==p and r['primary_delta']==0 for r in compared)) for p in (2,3,4)},
        comparisons_sha256=digest(data), training_admitted=False, production_changed=False,
        limitations=['aggregate_agreement_does_not_prove_per_match_equality',
                     '2025_GW1_positions_are_a_fixed_retrospective_hypothesis_for_2024_totals',
                     'goalkeepers_and_missing_provider_rows_not_synthesized_as_zero',
                     'tackles_won_is_sensitivity_not_a_selected_replacement',
                     'no_FPL_points_awarded_under_rules_that_did_not_exist_in_2024',
                     'document_acquired_now_not_historical_publication_proof',
                     'provider_action_definitions_still_require_reconciliation'])
    (out / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('core-root', 'annual-root', 'bootstrap-root', 'evidence-root', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.core_root, args.annual_root, args.bootstrap_root, args.evidence_root, args.out), indent=2))


if __name__ == '__main__':
    main()
