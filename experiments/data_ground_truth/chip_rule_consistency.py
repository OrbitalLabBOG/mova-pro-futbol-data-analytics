"""Audit declared chip squad constraints; consistency is not a complete rules interpreter."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from experiments.data_ground_truth import bootstrap_rules
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked


def nonempty(override):
    return any(v not in ({}, [], None) for v in override.values())


def constraints(sections, chip=None):
    settings = sections['game_settings']
    config = sections['game_config']['rules']
    roles = sections['element_types']
    if settings.get('squad_squadsize') != config.get('squad_squadsize'):
        return dict(status='conflicting_base_settings')
    override = chip['overrides'] if chip else {}
    if any(v not in ({}, [], None) for k, v in override.items() if k != 'rules'):
        return dict(status='unsupported_override')
    rules = override.get('rules') or {}
    if rules.keys() - {'squad_squadsize'}:
        return dict(status='unsupported_override')
    total = rules.get('squad_squadsize', settings.get('squad_squadsize'))
    if type(total) is not int or total <= 0:
        return dict(status='unknown_squad_total')
    if {r['id'] for r in roles} != {1, 2, 3, 4} or len(roles) != 4:
        return dict(status='unsupported_role_population')
    quota = [r.get('squad_select') for r in roles]
    if any(type(q) is not int or q < 0 for q in quota):
        return dict(status='unknown_role_quota')
    role_total = sum(quota)
    return dict(status='internally_consistent_squad_total' if total == role_total else 'inconsistent_squad_total',
                declared_squad_total=total, exact_role_quota_total=role_total,
                role_quotas={str(r['id']): r['squad_select'] for r in roles})


def window(chip, gw):
    start, stop = chip['start_event'], chip['stop_event']
    if any(type(x) is not int for x in (start, stop, gw)) or not 1 <= start <= stop <= 38 or not 1 <= gw <= 38:
        raise ValueError('invalid declared chip interval')
    return 'future' if gw < start else 'expired' if gw > stop else 'within_declared_window'


def build(base: Path, out: Path):
    parent = base / 'bootstrap-rules-v1'
    reproduced = out / 'rules_revalidated'
    bootstrap_rules.build(base / 'raw-bootstrap-snapshots', base / 'publication-selection-v1', reproduced)
    for name in ('report.json', 'snapshots.json', 'deadline_changes.json', 'rule_conflicts.json', 'chip_overrides.json'):
        if (parent / name).read_bytes() != (reproduced / name).read_bytes():
            raise ValueError('parent reproduction mismatch: ' + name)
    report_bytes = (parent / 'report.json').read_bytes()
    report = json.loads(report_bytes)
    snapshots = json.loads(checked(parent / 'snapshots.json', report['artifacts']['snapshots.json']))
    selected = [r for r in snapshots if r['season'] == '2025-26']
    if len(selected) != 38 or {r['gw'] for r in selected} != set(range(1, 39)):
        raise ValueError('incomplete target season')
    observations = []
    for row in selected:
        sections = json.loads(checked(parent / 'objects' / row['artifacts']['sections'], row['artifacts']['sections']))
        calendar = json.loads(checked(parent / 'objects' / row['artifacts']['calendar'], row['artifacts']['calendar']))
        if not row['publication_verified']:
            raise ValueError('unproven selected snapshot')
        chips = sections['chips']
        if len({c['id'] for c in chips}) != len(chips):
            raise ValueError('duplicate chip id')
        scenarios = []
        for chip in chips:
            scenarios.append(dict(chip=chip, temporal_scope=window(chip, row['gw']), audit=constraints(sections, chip)))
        observations.append(dict(season=row['season'], observed_gw=row['gw'], source_sha256=row['source_sha256'],
                                 source_claimed_at=row['source_claimed_at'], available_at=row['available_at'],
                                 sections_sha256=row['artifacts']['sections'], calendar_sha256=row['artifacts']['calendar'],
                                 base=constraints(sections), scenarios=scenarios,
                                 event_overrides=[e for e in calendar if nonempty(e.get('overrides') or {})],
                                 training_admitted=False))
    findings = [dict(observed_gw=r['observed_gw'], source_sha256=r['source_sha256'], **s)
                for r in observations for s in r['scenarios'] if s['audit']['status'] != 'internally_consistent_squad_total']
    payload = (json.dumps(observations, indent=2) + '\n').encode()
    (out / 'observations.json').write_bytes(payload)
    summary = dict(version='chip-rule-consistency-v1', season='2025-26', parent_report_sha256=digest(report_bytes),
                   implementation_sha256=digest(Path(__file__).read_bytes()), observations_sha256=digest(payload),
                   snapshots=len(observations), chip_observations=sum(len(r['scenarios']) for r in observations),
                   base_status=dict(Counter(r['base']['status'] for r in observations)),
                   chip_status=dict(Counter(s['audit']['status'] for r in observations for s in r['scenarios'])),
                   findings=findings, finding_temporal_scope=dict(Counter(f['temporal_scope'] for f in findings)),
                   nonempty_event_override_observations=sum(len(r['event_overrides']) for r in observations),
                   training_admitted=False, production_changed=False,
                   limitations=['checks_squad_total_and_exact_role_quotas_only',
                                'declared_chip_window_is_not_account_specific_availability',
                                'unsupported_overrides_not_silently_merged',
                                'does_not_establish_backend_precedence_or_rule_change_cause',
                                'future_inconsistency_does_not_prove_invalid_active_chip',
                                'later_snapshots_do_not_repair_earlier_observations'])
    (out / 'report.json').write_text(json.dumps(summary, indent=2) + '\n')
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base-root', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(build(a.base_root, a.out), indent=2))


if __name__ == '__main__':
    main()
