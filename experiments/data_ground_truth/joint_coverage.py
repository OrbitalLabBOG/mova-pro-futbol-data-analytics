"""Join frozen audit coverage; measure evidence availability, never training admission."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from experiments.data_ground_truth.bootstrap_time import aware
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked, verify

BASIC = ('minutes', 'total_points', 'goals_scored', 'assists', 'clean_sheets',
         'goals_conceded', 'saves', 'penalties_saved', 'penalties_missed',
         'yellow_cards', 'red_cards', 'bonus', 'bps')
EXPECTED = ('starts', 'expected_goals', 'expected_assists',
            'expected_goals_conceded', 'expected_goal_involvements')
PARENTS = {
    'selection': ('publication-selection-v1', '1ace4506377f6bf92ff79d71f7b1083070f273c58f802518754f96fccb87b6fc'),
    'calendar': ('calendar-evidence-index-v1', '14e03997f32311d934dfccfd20dc4d5530d863e0ee22b798d5f31ba3585c1514'),
    'screen': ('snapshot-field-screening-v1', 'c12f627afed8af1d706bdd7a81cf5b635ba56a486cb5a198da838bf55f690d1b'),
}


def keyed(rows):
    result = {}
    for row in rows:
        key = (row['season'], row['gw'])
        if key in result:
            raise ValueError('duplicate season/deadline')
        result[key] = row
    return result


def combine(targets, witnesses, calendars, screening, partitions):
    universe = keyed(targets)
    proof = keyed(witnesses)
    calendar = keyed(calendars)
    screens = keyed(screening)
    if screens.keys() != universe.keys():
        raise ValueError('screening population differs from target deadlines')
    for subset in (proof, calendar):
        if not subset.keys() <= universe.keys():
            raise ValueError('evidence outside target population')
        for key, row in subset.items():
            deadline = aware(universe[key]['deadline'])
            if aware(row['deadline']) != deadline or not aware(row['available_at']) < deadline:
                raise ValueError('conflicting deadline or evidence available too late')
    labels = {p['season']: p['rows'] for p in partitions}
    if len(labels) != len(partitions):
        raise ValueError('duplicate label season')
    windows = []
    for key, target in sorted(universe.items()):
        s = screens[key]
        p = proof.get(key)
        if p and (p['source_sha256'] != target['sha256'] or p['eligible_predeadline'] is not True):
            raise ValueError('publication does not bind selected snapshot')
        if s['published'] != (p is not None) or s['rows'] <= 0:
            raise ValueError('inconsistent screening publication/population')
        for counts in s['fields'].values():
            if any(v < 0 for v in counts.values()) or sum(counts.values()) != s['rows']:
                raise ValueError('inconsistent screening cell population')
        def all_pass(fields):
            return all(s['fields'].get(f, {}).get('screen_pass', 0) == s['rows'] for f in fields)
        both = p is not None and key in calendar
        c = calendar.get(key)
        windows.append(dict(season=key[0], gw=key[1], deadline=target['deadline'],
                            snapshot_sha256=target['sha256'], player_states=s['rows'],
                            label_season_present=key[0] in labels,
                            snapshot_publication_present=p is not None,
                            calendar_evidence_present=c is not None,
                            joint_evidence_present=both,
                            basic_fields_all_players_screen_pass=all_pass(BASIC),
                            expected_fields_all_players_screen_pass=all_pass(EXPECTED),
                            joint_basic_screen=both and all_pass(BASIC),
                            joint_expected_screen=both and all_pass(BASIC + EXPECTED),
                            calendar_source_clock_age_hours=c['source_clock_age_hours'] if c else None,
                            calendar_source_clock_kind=c['source_clock_kind'] if c else None,
                            training_admitted=False))
    seasons = []
    for season in sorted(labels.keys() | {s for s, _ in universe}):
        group = [r for r in windows if r['season'] == season]
        counts = {field: sum(r[field] for r in group) for field in (
            'snapshot_publication_present', 'calendar_evidence_present',
            'joint_evidence_present', 'joint_basic_screen', 'joint_expected_screen')}
        seasons.append(dict(season=season, label_rows=labels.get(season, 0),
                            observed_target_deadlines=len(group), **counts,
                            missing_joint_gws=[r['gw'] for r in group if not r['joint_evidence_present']],
                            target_universe_is_full_season=len(group) == 38 and {r['gw'] for r in group} == set(range(1, 39))))
    return windows, seasons


def build(base: Path, out: Path):
    reports = {k: json.loads(checked(base / root / 'report.json', sha))
               for k, (root, sha) in PARENTS.items()}
    selection, calendar, screen = (reports[k] for k in ('selection', 'calendar', 'screen'))
    if screen['selection_report_sha256'] != PARENTS['selection'][1] or calendar['target_parent_sha256'] != PARENTS['selection'][1]:
        raise ValueError('parent selection mismatch')
    def artifact(kind, name, sha):
        return json.loads(checked(base / PARENTS[kind][0] / name, sha))
    targets = artifact('selection', 'nominal_deadline_candidates.json', selection['artifacts']['nominal_deadline_candidates.json'])
    witnesses = artifact('selection', 'publication_witnesses.json', selection['artifacts']['publication_witnesses.json'])
    calendars = artifact('calendar', 'calendar_evidence.json', calendar['index_sha256'])
    checked(base / PARENTS['screen'][0] / 'screening.jsonl.gz', screen['screening_sha256'])
    pointer_path = Path(__file__).with_name('current-labels.json')
    pointer_bytes = pointer_path.read_bytes()
    pointer = json.loads(pointer_bytes)
    package = base / 'training-datasets' / pointer['dataset_id']
    manifest = json.loads(checked(package / 'manifest.json', pointer['manifest_sha256']))
    verify(package)
    windows, seasons = combine(targets, witnesses, calendars, screen['coverage'], manifest['partitions'])
    payload = (json.dumps(windows, indent=2) + '\n').encode()
    out.mkdir(parents=True, exist_ok=True)
    (out / 'windows.json').write_bytes(payload)
    report = dict(version='joint-data-coverage-v1', parent_report_sha256={k: v[1] for k, v in PARENTS.items()},
                  gt_dataset_id=pointer['dataset_id'], gt_pointer_sha256=digest(pointer_bytes),
                  implementation_sha256=digest(Path(__file__).read_bytes()),
                  windows_sha256=digest(payload), target_deadlines=len(windows),
                  label_rows=manifest['rows'], seasons=seasons,
                  training_admitted=False, production_changed=False,
                  limitations=['audit_composition_not_new_raw_acquisition',
                               'parent_artifact_hashes_verified_not_full_parent_reexecution',
                               'label_season_presence_is_not_player_state_label_join',
                               'target_universe_is_selected_bootstrap_deadlines_not_all_historical_deadlines',
                               'screen_pass_does_not_prove_semantics_identity_rules_or_replay_readiness',
                               'calendar_commit_age_is_not_API_capture_freshness',
                               'retrospective_label_agreement_never_filters_snapshot_population',
                               'own_collector_snapshot_evidence_not_substituted_for_selected_external_snapshot'])
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.base_root, args.out), indent=2))


if __name__ == '__main__':
    main()
