"""Typed experimental states from nominal deadline snapshots, without as-of admission."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
import gzip
import json
from pathlib import Path

import pandas as pd

from experiments.data_ground_truth.bootstrap_audit import decode, inspect
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked, verify

FLAGS = ('can_select', 'can_transact', 'removed', 'has_temporary_code')


def integer(value, field, minimum=1):
    if type(value) is not int or value < minimum:
        raise ValueError('invalid integer ' + field)
    return value


def percentage(value, field, nullable=False):
    if value is None and nullable:
        return None
    if isinstance(value, bool) or value is None:
        raise ValueError('invalid percentage ' + field)
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError('invalid percentage ' + field) from exc
    if not result.is_finite() or not 0 <= result <= 100:
        raise ValueError('invalid percentage ' + field)
    return str(result)


def normalize(element, teams, reference):
    eid = integer(element['id'], 'id')
    code = integer(element['code'], 'code')
    position = integer(element['element_type'], 'element_type')
    if position not in (1, 2, 3, 4, 5):
        raise ValueError('unknown element type')
    team = integer(element['team'], 'team')
    if team not in teams:
        raise ValueError('unknown snapshot team')
    cost = integer(element['now_cost'], 'now_cost')
    status = element['status']
    if status not in ('a', 'd', 'i', 'n', 's', 'u'):
        raise ValueError('unknown availability status')
    if position == 5:
        identity_status = 'manager_slot_not_player_identity'
    elif reference is None:
        identity_status = 'reference_season_unavailable'
    elif eid not in reference:
        identity_status = 'absent_from_label_reference'
    elif reference[eid] != code:
        raise ValueError('reference code conflict')
    else:
        identity_status = 'matched'
    result = dict(element=eid, official_player_code=code, team=team,
        snapshot_team_code=teams[team], position=position,
        entity_type='assistant_manager' if position == 5 else 'player',
        price_tenths_gbp=cost, price_gbp=str(Decimal(cost)/10), status=status,
        ownership_percent=percentage(element['selected_by_percent'], 'selected_by_percent'),
        reference_identity_status=identity_status, available_at=None,
        eligible_predeadline=False, eligible_training=False)
    for field in ('chance_of_playing_this_round', 'chance_of_playing_next_round'):
        result[field+'_present'] = field in element
        result[field] = percentage(element.get(field), field, nullable=True)
    for field in FLAGS:
        value = element.get(field)
        if value is not None and type(value) is not bool:
            raise ValueError('invalid optional boolean ' + field)
        result[field+'_present'] = field in element
        result[field] = value
    news_time = element.get('news_added')
    if news_time is not None:
        parsed = datetime.fromisoformat(news_time.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError('naive news timestamp')
    result['news_added'] = news_time
    result['news_added_present'] = 'news_added' in element
    return result


def build(root: Path, audit_root: Path, package: Path, out: Path):
    source = (root/'manifest.json').read_bytes()
    manifest = json.loads(source)
    if manifest['errors'] or len(manifest['records']) != manifest['expected_files']:
        raise ValueError('incomplete acquisition')
    audit = json.loads((audit_root/'report.json').read_text())
    if audit['manifest_sha256'] != digest(source) or audit['errors']:
        raise ValueError('audit source mismatch or errors')
    candidate_bytes = checked(audit_root/'nominal_deadline_candidates.json',
        audit['artifacts']['nominal_deadline_candidates.json'])
    candidates = json.loads(candidate_bytes)
    keys = [(c['season'], c['gw']) for c in candidates]
    if len(keys) != len(set(keys)):
        raise ValueError('duplicate candidate deadline')
    reference_manifest = verify(package)
    references = {}
    for partition in reference_manifest['partitions']:
        frame = pd.read_csv(package/partition['file'])[['element', 'official_player_code']].drop_duplicates()
        if frame.element.duplicated().any():
            raise ValueError('ambiguous reference element')
        references[partition['season']] = {int(r.element): int(r.official_player_code)
            for r in frame.itertuples() if pd.notna(r.official_player_code)}
    records = {r['path']: r for r in manifest['records']}
    rows, rejected = [], []
    for candidate in candidates:
        record = records[candidate['path']]
        if record['sha256'] != candidate['sha256']:
            raise ValueError('candidate source mismatch')
        snapshot = decode(checked(root/'objects'/record['sha256'], record['sha256']))
        _, actual = inspect(snapshot, record['path'])
        matching = [c for c in actual if c['season'] == candidate['season'] and c['gw'] == candidate['gw']]
        if len(matching) != 1 or matching[0]['deadline'] != candidate['deadline'] or matching[0]['source_claimed_at'] != candidate['source_claimed_at']:
            raise ValueError('candidate calendar mismatch')
        teams = {integer(t['id'], 'team id'): integer(t['code'], 'team code') for t in snapshot['teams']}
        if len(teams) != len(snapshot['teams']):
            raise ValueError('duplicate snapshot team')
        elements = snapshot['elements']
        player_codes = [e['code'] for e in elements if e['element_type'] != 5]
        if len(player_codes) != len(set(player_codes)):
            raise ValueError('ambiguous snapshot player code')
        context = dict(season=candidate['season'], gw=candidate['gw'], deadline=candidate['deadline'],
            source_claimed_at=candidate['source_claimed_at'], source_sha256=record['sha256'],
            clock_assumption='UTC_for_nominal_selection_only',
            season_scope='open' if candidate['season'] > '2025-26' else 'closed')
        for element in elements:
            try:
                row = normalize(element, teams, references.get(candidate['season']))
                rows.append(dict(**context, **row))
            except (ValueError, KeyError, TypeError) as exc:
                rejected.append(dict(**context, element=element.get('id'), source_code=element.get('code'),
                    reference_code=(references.get(candidate['season']) or {}).get(element.get('id'))
                    if type(element.get('id')) is int else None, error=str(exc)))
    frame = pd.DataFrame(rows)
    seasons = {}
    for season, group in frame.groupby('season'):
        players = group[group.entity_type.eq('player')]
        seasons[season] = dict(rows=len(group), player_rows=len(players), manager_rows=len(group)-len(players),
            deadlines=int(group.gw.nunique()), identity_status=dict(Counter(players.reference_identity_status)),
            flags={f: dict(present=int(players[f+'_present'].sum()), nonnull=int(players[f].notna().sum()),
                           true=int(players[f].eq(True).sum()), false=int(players[f].eq(False).sum())) for f in FLAGS})
    out.mkdir(parents=True, exist_ok=True)
    artifacts = {}
    players = frame[frame.entity_type.eq('player')]
    managers = frame[frame.entity_type.eq('assistant_manager')].rename(columns={'official_player_code': 'source_element_code'})
    for name, payload in [('player_states.csv.gz', gzip.compress(players.to_csv(index=False).encode(), mtime=0)),
                           ('manager_states.csv.gz', gzip.compress(managers.to_csv(index=False).encode(), mtime=0)),
                           ('rejected.json', (json.dumps(rejected, indent=2)+'\n').encode())]:
        (out/name).write_bytes(payload)
        artifacts[name] = digest(payload)
    report = dict(version='bootstrap-state-v1', source_manifest_sha256=digest(source),
        candidate_sha256=digest(candidate_bytes), reference_dataset_id=reference_manifest['dataset_id'],
        implementation_sha256=digest(Path(__file__).read_bytes()), candidates=len(candidates),
        rows=len(rows), rejected_rows=len(rejected), seasons=seasons, artifacts=artifacts,
        eligible_predeadline=False, eligible_training=False,
        semantics='published_source_roster_is_not_proof_of_buy_or_lineup_eligibility')
    (out/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for arg in ('root', 'audit-root', 'package', 'out'):
        ap.add_argument('--'+arg, type=Path, required=True)
    args = ap.parse_args()
    print(json.dumps(build(args.root, args.audit_root, args.package, args.out), indent=2))


if __name__ == '__main__':
    main()
