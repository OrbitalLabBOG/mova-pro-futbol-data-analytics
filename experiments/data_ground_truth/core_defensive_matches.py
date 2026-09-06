"""Link provider defensive observations to FPL fixtures without equating definitions."""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

import pandas as pd

from experiments.data_ground_truth.complement import unique_observations
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked, verify

FIELDS = ['tackles', 'tackles_won', 'interceptions', 'recoveries', 'blocks', 'clearances']
PREFIX = 'data/2024-2025/'


def fixture_links(matches, fixtures, teams):
    """Use directed club codes and dates; never source GW or synthetic match ID."""
    if teams.id.duplicated().any() or teams.code.duplicated().any():
        raise ValueError('ambiguous official team map')
    mapping = teams.set_index('id').code
    official = fixtures[['id', 'team_h', 'team_a', 'kickoff_time']].copy()
    official['home_team'] = official.team_h.map(mapping)
    official['away_team'] = official.team_a.map(mapping)
    official['date'] = pd.to_datetime(official.kickoff_time, utc=True, errors='raise').dt.strftime('%Y-%m-%d')
    core = matches.copy()
    # The provider clock is naive. Calendar-date equality is not timezone proof.
    core['date'] = pd.to_datetime(core.kickoff_time, format='ISO8601', errors='raise').dt.strftime('%Y-%m-%d')
    keys = ['home_team', 'away_team', 'date']
    if official[keys].isna().any().any() or core[keys].isna().any().any():
        raise ValueError('missing fixture join key')
    if official.duplicated(keys).any() or core.duplicated(keys).any():
        raise ValueError('ambiguous directed fixture date')
    return core.merge(official[keys + ['id']], on=keys, how='left', validate='one_to_one')


def build(raw_root, package, out):
    manifest_bytes = (raw_root / 'manifest.json').read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest['errors']:
        raise ValueError('raw acquisition errors')
    records = []
    tables = {}
    for record in manifest['records']:
        path = record['path']
        kind = None
        if record['repository'] == 'olbauday/FPL-Core-Insights':
            if path.startswith(PREFIX + 'playermatchstats/GW') and path.endswith('/playermatchstats.csv'):
                kind = 'stats'
            elif path.startswith(PREFIX + 'matches/GW') and path.endswith('/matches.csv'):
                kind = 'matches'
            elif path == PREFIX + 'players/players.csv':
                kind = 'players'
        elif record['repository'] == 'vaastav/Fantasy-Premier-League':
            kind = {'data/2024-25/fixtures.csv': 'fixtures', 'data/2024-25/teams.csv': 'teams'}.get(path)
        if kind is None:
            continue
        body = checked(raw_root / 'objects' / record['sha256'], record['sha256'])
        if len(body) != record['bytes']:
            raise ValueError('raw size mismatch')
        tables.setdefault(kind, []).append(pd.read_csv(io.BytesIO(body)))
        records.append(dict(path=path, sha256=record['sha256'], kind=kind))
    for kind in ('players', 'fixtures', 'teams'):
        if len(tables.get(kind, [])) != 1:
            raise ValueError('missing or ambiguous reference table')
    stats, stats_quality = unique_observations(pd.concat(tables['stats'], ignore_index=True)[
        ['player_id', 'match_id', 'minutes_played'] + FIELDS], ['player_id', 'match_id'])
    matches, matches_quality = unique_observations(pd.concat(tables['matches'], ignore_index=True)[
        ['match_id', 'home_team', 'away_team', 'kickoff_time']], ['match_id'])
    players, player_quality = unique_observations(tables['players'][0][['player_id', 'player_code']], ['player_id'])
    links = fixture_links(matches, tables['fixtures'][0], tables['teams'][0])
    dataset = verify(package)
    partition = next(p for p in dataset['partitions'] if p['season'] == '2024-25')
    labels = pd.read_csv(package / partition['file'])
    official = labels[['element', 'official_player_code']].drop_duplicates()
    if official.element.duplicated().any() or official.official_player_code.duplicated().any():
        raise ValueError('ambiguous GT identity')
    identities = players.merge(official, left_on='player_id', right_on='element', how='left', validate='one_to_one')
    identities['identity_agrees'] = identities.player_code.eq(identities.official_player_code)
    stats = stats.merge(links[['match_id', 'id']], on='match_id', how='left', validate='many_to_one')
    stats = stats.merge(identities[['player_id', 'player_code', 'identity_agrees']], on='player_id', how='left', validate='many_to_one')
    stats['official_player_code'] = stats.player_code.where(stats.identity_agrees.eq(True))
    stats = stats.rename(columns={'id': 'fixture'})
    stats = stats.merge(labels[['fixture', 'official_player_code', 'minutes']], on=['fixture', 'official_player_code'],
                        how='left', validate='one_to_one', indicator=True)
    paired = stats['_merge'].eq('both')
    matched_keys = set(zip(stats.loc[paired, 'fixture'], stats.loc[paired, 'official_player_code']))
    missing = labels.loc[labels.minutes.gt(0) & ~pd.Series(
        [(f, c) in matched_keys for f, c in zip(labels.fixture, labels.official_player_code)], index=labels.index)]
    field_coverage = {}
    for field in FIELDS:
        values = pd.to_numeric(stats[field], errors='raise')
        valid = values.notna() & values.ge(0) & values.mod(1).eq(0)
        field_coverage[field] = dict(valid=int(valid.sum()), missing=int(values.isna().sum()),
            invalid=int((values.notna() & ~valid).sum()), positive=int(values.gt(0).sum()), zero=int(values.eq(0).sum()))
    stats['eligible_predeadline'] = False
    stats['training_admitted'] = False
    out.mkdir(parents=True, exist_ok=True)
    for name, frame in [('observations.csv', stats), ('fixture-links.csv', links),
                        ('missing-positive-appearances.csv', missing[['element', 'official_player_code', 'fixture', 'gw', 'minutes']])]:
        frame.to_csv(out / name, index=False)
    result = dict(version='core-defensive-matches-v1', season='2024-25',
        raw_manifest_sha256=digest(manifest_bytes), dataset_id=dataset['dataset_id'],
        implementation_sha256=digest(Path(__file__).read_bytes()), source_records=records,
        stats_quality=stats_quality, matches_quality=matches_quality, player_quality=player_quality,
        linked_fixtures=int(links.id.notna().sum()), unmatched_source_fixtures=int(links.id.isna().sum()),
        reference_fixtures=len(tables['fixtures'][0]), fixtures_with_stats=int(stats.fixture.nunique()),
        identity_agree_players=int(identities.identity_agrees.sum()),
        identity_disagree_players=int((identities.element.notna() & ~identities.identity_agrees).sum()),
        identity_without_GT_players=int(identities.element.isna().sum()),
        paired_rows=int(paired.sum()), unpaired_rows=int((~paired).sum()),
        minutes_equal=int((paired & stats.minutes_played.eq(stats.minutes)).sum()),
        minutes_different=int((paired & stats.minutes_played.ne(stats.minutes)).sum()),
        minutes_delta_counts={str(k): int(v) for k, v in
            (stats.loc[paired, 'minutes_played'] - stats.loc[paired, 'minutes']).value_counts().sort_index().items()},
        provider_minutes_missing=int(stats.minutes_played.isna().sum()),
        provider_minutes_outside_0_90=int((stats.minutes_played.lt(0) | stats.minutes_played.gt(90)).sum()),
        positive_GT_appearances=int(labels.minutes.gt(0).sum()), missing_positive_GT_appearances=len(missing),
        field_coverage=field_coverage,
        artifacts={n: digest((out / n).read_bytes()) for n in ['observations.csv', 'fixture-links.csv', 'missing-positive-appearances.csv']},
        training_admitted=False, production_changed=False,
        limitations=['provider_fields_not_assumed_FPL_equivalent',
                     'naive_source_date_matched_to_official_UTC_date_not_clock_proof',
                     'field_presence_does_not_prove_complete_measurement',
                     'identity_code_agreement_not_independent_person_proof',
                     'matched_minutes_do_not_admit_defensive_labels',
                     'no_new_complete_FPL_season_or_FPL_score_reconstruction',
                     'retrospective_values_without_predeadline_publication_proof'])
    (out / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('raw-root', 'package', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.raw_root, args.package, args.out), indent=2))


if __name__ == '__main__':
    main()
