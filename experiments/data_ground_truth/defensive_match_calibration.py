"""Compare provider defensive observations with FPL components by match."""
from __future__ import annotations

import argparse
from collections import Counter
import gzip
import io
import json
from pathlib import Path

import pandas as pd

from experiments.data_ground_truth.complement import unique_observations
from experiments.data_ground_truth.core_defensive_matches import FIELDS, fixture_links
from experiments.data_ground_truth.defensive_annual_reconciliation import composition
from experiments.data_ground_truth.preseason_supplemental import code_key
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked, verify

METRICS = {'tackles': 'tackles', 'recoveries': 'recoveries',
           'cbi_sum': 'clearances_blocks_interceptions',
           'native_contribution': 'defensive_contribution',
           'derived_contribution': 'defensive_contribution'}


def count(value):
    if value is None or pd.isna(value):
        return None
    if isinstance(value, bool) or not float(value).is_integer() or value < 0:
        raise ValueError('invalid provider count')
    return int(value)


def compare_value(provider, official):
    if provider is None:
        return dict(status='provider_unknown')
    if official is None:
        return dict(status='no_FPL_reference')
    if official['status'] != 'valid':
        return dict(status='FPL_' + official['status'])
    value = official['value']
    return dict(status='equal' if provider == value else 'different', provider_value=provider,
                FPL_value=value, delta=provider-value)


def stratum(row):
    if row['FPL_minutes'] is None or row['position'] not in (1,2,3,4):
        return 'unknown_minutes_or_position'
    if row['FPL_minutes'] == 0:
        return 'zero_FPL_minutes'
    return 'played_goalkeepers' if row['position'] == 1 else 'played_outfield'


def build(raw_root, supplemental_root, package, out):
    raw_bytes = (raw_root / 'manifest.json').read_bytes()
    manifest = json.loads(raw_bytes)
    if manifest['errors']:
        raise ValueError('raw acquisition errors')
    tables = {}; sources = []
    for record in manifest['records']:
        path = record['path']; kind = None
        if record['repository'] == 'olbauday/FPL-Core-Insights' and path.startswith('data/2025-2026/By Gameweek/GW'):
            kind = {'matches.csv': 'matches', 'playermatchstats.csv': 'stats', 'players.csv': 'players'}.get(Path(path).name)
        elif record['repository'] == 'vaastav/Fantasy-Premier-League':
            kind = {'data/2025-26/fixtures.csv': 'fixtures', 'data/2025-26/teams.csv': 'teams',
                    'data/2025-26/players_raw.csv': 'official_players'}.get(path)
        if kind is None:
            continue
        body = checked(raw_root / 'objects' / record['sha256'], record['sha256'])
        if len(body) != record['bytes']:
            raise ValueError('source size mismatch')
        tables.setdefault(kind, []).append(pd.read_csv(io.BytesIO(body)))
        sources.append(dict(path=path, sha256=record['sha256'], kind=kind))
    for kind in ('fixtures', 'teams', 'official_players'):
        if len(tables.get(kind, [])) != 1:
            raise ValueError('ambiguous reference table')
    matches, mq = unique_observations(pd.concat(tables['matches'], ignore_index=True)[
        ['match_id', 'home_team', 'away_team', 'kickoff_time', 'tournament']], ['match_id'])
    original_match_times = matches.copy()
    # Preserve date in the stated timezone; do not infer a timezone for naive values.
    matches['kickoff_time'] = matches.kickoff_time.map(lambda x: pd.Timestamp(x).date().isoformat())
    prem = matches.loc[matches.tournament.eq('prem')]
    links = fixture_links(prem, tables['fixtures'][0], tables['teams'][0])
    if links.id.isna().any():
        raise ValueError('unmatched Premier League fixture')
    stats, sq = unique_observations(pd.concat(tables['stats'], ignore_index=True)[
        ['player_id', 'match_id', 'minutes_played', 'defensive_contributions'] + FIELDS], ['player_id', 'match_id'])
    players, pq = unique_observations(pd.concat(tables['players'], ignore_index=True)[
        ['player_id', 'player_code']], ['player_id'])
    stats = stats.merge(matches[['match_id', 'tournament']], on='match_id', how='left', validate='many_to_one')
    excluded = dict(stats.tournament.fillna('unknown_match').value_counts())
    stats = stats.loc[stats.tournament.eq('prem')].copy()
    stats = stats.merge(links[['match_id', 'id']], on='match_id', how='left', validate='many_to_one').rename(columns={'id': 'fixture'})
    stats = stats.merge(players, on='player_id', how='left', validate='many_to_one')
    dataset = verify(package)
    partition = next(p for p in dataset['partitions'] if p['season'] == '2025-26')
    labels = pd.read_csv(package / partition['file'])
    identity = labels[['element', 'official_player_code']].drop_duplicates()
    if identity.element.duplicated().any() or identity.official_player_code.duplicated().any():
        raise ValueError('ambiguous GT identity')
    stats = stats.merge(identity, left_on='player_id', right_on='element', how='left', validate='many_to_one')
    identity_ok = stats.player_code.eq(stats.official_player_code)
    stats['official_player_code'] = stats.official_player_code.where(identity_ok)
    official = tables['official_players'][0][['id', 'code', 'element_type']]
    if official.id.duplicated().any():
        raise ValueError('ambiguous FPL position')
    stats = stats.merge(official, left_on='player_id', right_on='id', how='left', validate='many_to_one')
    stats['element_type'] = stats.element_type.where(stats.code.eq(stats.official_player_code))
    supplemental_bytes = (supplemental_root / 'report.json').read_bytes()
    supplemental = json.loads(supplemental_bytes)
    if supplemental['dataset_id'] != dataset['dataset_id']:
        raise ValueError('supplemental GT mismatch')
    payload = checked(supplemental_root / 'components.jsonl.gz', supplemental['artifacts']['components.jsonl.gz'])
    refs = {}
    for line in gzip.decompress(payload).splitlines():
        row = json.loads(line)
        if row['season'] != '2025-26':
            continue
        key = (row['fixture'], code_key(row['official_player_code']))
        if key in refs:
            raise ValueError('duplicate FPL component key')
        refs[key] = row['cells']
    output = []; paired_keys = set()
    gt_keys = set(zip(labels.fixture, labels.official_player_code.map(code_key)))
    gt_context = {(int(r.fixture), code_key(r.official_player_code)): (int(r.minutes), int(r.gw))
                  for r in labels.itertuples()}
    for row in stats.to_dict('records'):
        code = None if pd.isna(row['official_player_code']) else code_key(int(row['official_player_code']))
        key = (int(row['fixture']), code)
        reference = refs.get(key)
        if key in gt_keys:
            paired_keys.add(key)
        actions = {f: count(row[f]) for f in FIELDS}
        cbi = None if any(actions[f] is None for f in ['clearances', 'blocks', 'interceptions']) else sum(actions[f] for f in ['clearances', 'blocks', 'interceptions'])
        position = None if pd.isna(row['element_type']) else int(row['element_type'])
        values = dict(tackles=actions['tackles'], recoveries=actions['recoveries'], cbi_sum=cbi,
                      native_contribution=count(row['defensive_contributions']),
                      derived_contribution=composition(actions, position))
        comparisons = {metric: compare_value(value, reference.get(METRICS[metric]) if reference else None)
                       for metric, value in values.items()}
        minutes, gw = gt_context.get(key, (None, None))
        output.append(dict(player_id=int(row['player_id']), fixture=key[0], source_code=code,
            source_match_id=row['match_id'], provider_actions=actions,
            provider_native_contribution=values['native_contribution'],
            position=position, FPL_minutes=minutes, FPL_gw=gw,
            reference_present=reference is not None, comparisons=comparisons,
            training_admitted=False, eligible_predeadline=False))
    positive = set(zip(labels.loc[labels.minutes.gt(0), 'fixture'], labels.loc[labels.minutes.gt(0), 'official_player_code'].map(code_key)))
    out.mkdir(parents=True, exist_ok=True)
    data = gzip.compress(('\n'.join(json.dumps(r, sort_keys=True) for r in output) + '\n').encode(), mtime=0)
    (out / 'comparisons.jsonl.gz').write_bytes(data)
    missing = sorted(positive - paired_keys)
    (out / 'missing-positive-appearances.json').write_text(json.dumps(missing, indent=2) + '\n')
    strata = {name:[] for name in ['played_outfield','played_goalkeepers','zero_FPL_minutes','unknown_minutes_or_position']}
    for row in output:
        strata[stratum(row)].append(row)
    result = dict(version='defensive-match-calibration-v1', season='2025-26',
        raw_manifest_sha256=digest(raw_bytes), supplemental_report_sha256=digest(supplemental_bytes),
        dataset_id=dataset['dataset_id'], implementation_sha256=digest(Path(__file__).read_bytes()), source_records=sources,
        matches_quality=mq, stats_quality=sq, players_quality=pq,
        source_match_tournaments={str(k):int(v) for k,v in original_match_times.tournament.value_counts().items()},
        source_row_tournaments={str(k):int(v) for k,v in excluded.items()}, linked_premier_fixtures=len(links),
        rows=len(output), identity_unresolved_rows=int((~identity_ok).sum()),
        rows_with_FPL_reference=sum(r['reference_present'] for r in output),
        positive_GT_appearances=len(positive), missing_positive_GT_appearances=len(missing),
        comparisons={metric:dict(Counter(r['comparisons'][metric]['status'] for r in output)) for metric in METRICS},
        provider_action_coverage={f:dict(Counter('unknown' if r['provider_actions'][f] is None else
            'zero' if r['provider_actions'][f]==0 else 'positive' for r in output)) for f in FIELDS},
        strata={name:dict(rows=len(rows), comparisons={metric:dict(Counter(r['comparisons'][metric]['status'] for r in rows))
                 for metric in METRICS}) for name,rows in strata.items()},
        artifacts={n:digest((out/n).read_bytes()) for n in ['comparisons.jsonl.gz','missing-positive-appearances.json']},
        training_admitted=False, production_changed=False,
        limitations=['same_match_comparison_not_independent_provider_error_estimate',
                     'native_contribution_upstream_provenance_requires_review',
                     'goalkeeper_derived_contribution_unknown_not_zero',
                     'unknown_components_not_imputed_or_filtered_by_agreement',
                     'no_assumption_of_2024_per_match_equivalence_from_2025_agreement',
                     'retrospective_fields_without_predeadline_publication_proof'])
    (out/'report.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('raw-root','supplemental-root','package','out'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(build(args.raw_root,args.supplemental_root,args.package,args.out),indent=2))


if __name__=='__main__':
    main()
