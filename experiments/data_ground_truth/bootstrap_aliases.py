"""Corroborate season-scoped FPL player code transitions, never manager replacements."""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

import pandas as pd

from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked, verify


def corroborate(entry, target_code, appearance_dates, collision_codes=()):
    variants = entry['variants']
    if any(v['position'] not in (1, 2, 3, 4) for v in variants):
        raise ValueError('manager or mixed entity slot')
    codes = {v['code'] for v in variants}
    if len(codes) != 2 or target_code not in codes:
        raise ValueError('unanchored or complex code transition')
    if codes.intersection(collision_codes):
        raise ValueError('code shared by other elements')
    source_code = next(iter(codes - {target_code}))
    old = [v for v in variants if v['code'] == source_code]
    new = [v for v in variants if v['code'] == target_code]
    before = max(old, key=lambda v: v['last']['source_claimed_at'])
    after = min(new, key=lambda v: v['first']['source_claimed_at'])
    if before['last']['source_claimed_at'] >= after['first']['source_claimed_at']:
        raise ValueError('overlapping or reversed code observations')
    if any(before[k] != after[k] for k in ('first_name', 'second_name', 'position')):
        raise ValueError('boundary name or position disagreement')
    if not set(before['observed_team_ids']).intersection(after['observed_team_ids']):
        raise ValueError('no shared observed club')
    if min(before['distinct_snapshot_objects'], after['distinct_snapshot_objects']) < 2:
        raise ValueError('insufficient distinct snapshots')
    dates = sorted(set(appearance_dates))
    if len(dates) < 2:
        raise ValueError('insufficient corroborated appearance dates')
    return dict(season=entry['season'], element=entry['element'], source_code=source_code,
        canonical_code=target_code, first_source_claimed_at=min(v['first']['source_claimed_at'] for v in old),
        last_source_claimed_at=before['last']['source_claimed_at'], before=before, after=after,
        corroborated_appearance_dates=dates, scope='same_season_fpl_element_only',
        evidence_status='retrospective_source_continuity_and_appearance_corroboration', eligible_predeadline=False)


def build(identity_root: Path, sport_root: Path, package: Path, out: Path):
    identity_bytes = (identity_root/'report.json').read_bytes()
    identity = json.loads(identity_bytes)
    if identity['errors']:
        raise ValueError('identity audit errors')
    changes = json.loads(checked(identity_root/'code_changes.json', identity['artifacts']['code_changes.json']))
    collisions = json.loads(checked(identity_root/'code_collisions.json', identity['artifacts']['code_collisions.json']))
    reference = verify(package)
    parts = {p['season']: p for p in reference['partitions']}
    sport_report = json.loads((sport_root/'report.json').read_text())
    aliases, rejected, sport_hashes = [], [], {}
    for entry in changes:
        season = entry['season']
        if 5 in entry['entity_types']:
            rejected.append(dict(season=season, element=entry['element'], reason='manager replacement excluded'))
            continue
        frame = pd.read_csv(package/parts[season]['file'])
        player = frame[frame.element.eq(entry['element'])]
        codes = player.official_player_code.dropna().unique()
        if len(codes) != 1:
            raise ValueError('ambiguous label identity')
        target = int(codes[0])
        sha = sport_report['seasons'][season]['artifact_sha256']
        sport_hashes[season] = sha
        sports = pd.read_csv(io.BytesIO(checked(sport_root/'archive'/season/'observations.csv', sha)))
        sports = sports[sports.official_player_code.eq(target) & sports.minutesPlayed.gt(0)]
        player = player[player.minutes.gt(0)]
        fpl_dates = set(pd.to_datetime(player.event_time_utc, utc=True).dt.tz_convert('Europe/London').dt.date.astype(str))
        sport_dates = set(pd.to_datetime(sports.kickoff).dt.date.astype(str))
        try:
            aliases.append(corroborate(entry, target, fpl_dates & sport_dates,
                {r['code'] for r in collisions if r['season'] == season}))
        except ValueError as exc:
            rejected.append(dict(season=season, element=entry['element'], reason=str(exc)))
    out.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(aliases, indent=2)+'\n').encode()
    (out/'aliases.json').write_bytes(payload)
    report = dict(version='bootstrap-aliases-v1', source_manifest_sha256=identity['manifest_sha256'],
        identity_report_sha256=digest(identity_bytes), reference_dataset_id=reference['dataset_id'],
        implementation_sha256=digest(Path(__file__).read_bytes()), sport_sha256=sport_hashes,
        aliases=len(aliases), rejected=rejected, aliases_sha256=digest(payload),
        temporal_admission=False, rule='same_season_element_boundary_identity_and_two_matching_positive_appearance_dates')
    (out/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for arg in ('identity-root', 'sport-root', 'package', 'out'):
        ap.add_argument('--'+arg, type=Path, required=True)
    args = ap.parse_args()
    print(json.dumps(build(args.identity_root, args.sport_root, args.package, args.out), indent=2))


if __name__ == '__main__':
    main()
