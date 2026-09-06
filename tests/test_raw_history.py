import json

import pandas as pd
import pytest

from experiments.data_ground_truth import raw
from experiments.data_ground_truth.audit import frame_quality


def test_capture_verifies_cache_and_never_invents_availability(tmp_path, monkeypatch):
    calls = []
    def get(url):
        calls.append(url)
        return b'id,minutes\n1,90\n'
    monkeypatch.setattr(raw, '_get', get)
    record = raw.capture(tmp_path, raw.REPOS[0], 'a' * 40, 'data/example.csv')
    assert record['available_at'] is None
    assert record['eligible_predeadline'] is False
    assert raw.capture(tmp_path, raw.REPOS[0], 'a' * 40, 'data/example.csv') == record
    assert len(calls) == 1
    (tmp_path / 'objects' / record['sha256']).write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='corrupt'):
        raw.capture(tmp_path, raw.REPOS[0], 'a' * 40, 'data/example.csv')


@pytest.mark.parametrize('revision,path', [('main', 'data/x.csv'), ('a'*40, '../x'), ('a'*40, '/x')])
def test_capture_rejects_unpinned_or_unsafe_source(tmp_path, revision, path):
    with pytest.raises(ValueError):
        raw.capture(tmp_path, raw.REPOS[0], revision, path)


def test_quality_distinguishes_double_gameweek_nulls_and_name_collision():
    frame = pd.DataFrame([
        dict(season='2025-26', gw=26, element=1, fixture=10, player_key='same name', minutes=90, kickoff_time='2026-02-01T12:00:00Z', xg=None),
        dict(season='2025-26', gw=26, element=1, fixture=11, player_key='same name', minutes=0, kickoff_time='2026-02-03T12:00:00Z', xg=0),
        dict(season='2025-26', gw=26, element=2, fixture=10, player_key='same name', minutes=95, kickoff_time='bad', xg=1),
    ])
    report = frame_quality(frame)
    assert report['duplicate_keys'] == 0
    assert report['ambiguous_name_keys'] == {'same name': 2}
    assert report['invalid_minutes'] == report['invalid_kickoff'] == 1
    assert report['columns']['xg'] == dict(non_null=2, rows=3, played_non_null=1, played_rows=2)


def test_selection_avoids_tournament_replication():
    assert raw.select(raw.REPOS[1], 'data/2025-2026/By Gameweek/GW0/playermatchstats.csv')
    assert not raw.select(raw.REPOS[1], 'data/2025-2026/By Tournament/Premier League/GW1/playermatchstats.csv')
    assert raw.select(raw.REPOS[0], 'data/2016-17/gws/merged_gw.csv')


def test_conflicting_observations_are_quarantined_not_last_write_wins():
    from experiments.data_ground_truth.complement import unique_observations
    frame = pd.DataFrame([{'id': 1, 'minutes': 90}, {'id': 1, 'minutes': 90},
                          {'id': 2, 'minutes': 0}, {'id': 2, 'minutes': 12},
                          {'id': None, 'minutes': 90}])
    retained, report = unique_observations(frame, ['id'])
    assert retained.id.tolist() == [1]
    assert report == dict(input_rows=5, exact_duplicates=1, conflicting_rows=2, null_key_rows=1, retained_rows=1)


def test_mixed_timestamp_formats_are_not_false_missing_values():
    frame = pd.DataFrame([
        dict(season='2025-26', gw=1, element=1, fixture=1, player_key='a', minutes=90, kickoff_time='2025-08-16T16:30:00+00:00'),
        dict(season='2025-26', gw=2, element=1, fixture=2, player_key='a', minutes=90, kickoff_time='2025-08-23 16:30:00'),
    ])
    assert frame_quality(frame)['invalid_kickoff'] == 0


def test_reconciliation_checks_official_identity_and_double_gameweeks(tmp_path):
    import sqlite3
    from experiments.data_ground_truth.complement import reconcile
    root = tmp_path / 'raw'
    (root / 'objects').mkdir(parents=True)
    records = []
    sources = {
        'matches': pd.DataFrame([dict(match_id='cup1', kickoff_time=None, tournament='efl-cup', finished=True)]),
        'playermatchstats': pd.DataFrame([dict(match_id='cup1', player_id=1, minutes_played=90)]),
        'players': pd.DataFrame([dict(player_id=1, player_code=99)]),
        'player_gameweek_stats': pd.DataFrame([dict(id=1, gw=26, total_points=10, minutes=180)]),
    }
    for kind, df in sources.items():
        data = df.to_csv(index=False).encode()
        sha = raw.digest(data)
        (root / 'objects' / sha).write_bytes(data)
        records.append(dict(repository=raw.REPOS[1], path=f'data/2025-2026/By Gameweek/GW26/{kind}.csv', sha256=sha))
    (root / 'manifest.json').write_text(json.dumps(dict(records=records)))
    identity = root / 'staging' / '2025-26'
    identity.mkdir(parents=True)
    pd.DataFrame([dict(element=1, official_player_code=100)]).to_csv(identity / 'player_identity.csv', index=False)
    db = tmp_path / 'canonical.db'
    with sqlite3.connect(db) as con:
        pd.DataFrame([dict(season='2025-26', element=1, gw=26, total_points=4, minutes=90),
                      dict(season='2025-26', element=1, gw=26, total_points=6, minutes=90)]).to_sql('player_gameweek', con, index=False)
    report = reconcile(db, root)['2025-2026']
    assert report['identity_reconciliation']['code_disagreements'] == 1
    assert report['weekly_reconciliation']['paired_rows'] == 1
    assert report['weekly_reconciliation']['points_disagreements'] == 0
    assert report['weekly_reconciliation']['minutes_disagreements'] == 0
    assert report['player_rows_without_valid_kickoff'] == 1
    staging = pd.read_csv(root / 'staging' / '2025-2026' / 'player_match_observations.csv')
    assert staging.source_available_at.isna().all()
    assert not staging.eligible_predeadline.any()
