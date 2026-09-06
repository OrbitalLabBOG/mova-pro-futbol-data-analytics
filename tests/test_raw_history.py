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


def test_decoding_only_accepts_reviewed_latin1_hash(monkeypatch):
    from experiments.data_ground_truth import decoding
    data = 'name,minutes\nDoucouré,90\n'.encode('latin1')
    with pytest.raises(UnicodeDecodeError):
        decoding.read_csv_bytes(data)
    monkeypatch.setattr(decoding, 'LATIN1_HASHES', {raw.digest(data)})
    frame, encoding = decoding.read_csv_bytes(data)
    assert frame.name.tolist() == ['Doucouré']
    assert encoding == 'iso-8859-1'
    with pytest.raises(ValueError, match='replacement'):
        decoding.read_csv_bytes('name\nDoucour�\n'.encode())


def test_label_pack_resolves_identity_and_rejects_changed_ground_truth(tmp_path):
    import sqlite3
    from experiments.data_ground_truth.labels import build_labels
    root = tmp_path / 'raw'
    (root / 'objects').mkdir(parents=True)
    frame = pd.DataFrame([dict(GW=1, element=1, fixture=1, name='Same Name', minutes=90, total_points=4)])
    metadata = pd.DataFrame([dict(id=1, code=12345, element_type=2)])
    records = []
    for path, df in [('data/2025-26/gws/merged_gw.csv', frame), ('data/2025-26/players_raw.csv', metadata)]:
        data = df.to_csv(index=False).encode(); sha = raw.digest(data)
        (root / 'objects' / sha).write_bytes(data)
        records.append(dict(repository=raw.REPOS[0], path=path, sha256=sha))
    (root / 'manifest.json').write_text(json.dumps(dict(records=records)))
    db = tmp_path / 'canonical.db'
    with sqlite3.connect(db) as con:
        frame.rename(columns={'GW':'gw'}).assign(season='2025-26').to_sql('player_gameweek', con, index=False)
    result = build_labels(root, db)
    assert result['seasons']['2025-26']['unresolved_identities'] == 0
    labels = pd.read_csv(root / 'labels' / '2025-26.csv')
    assert labels.official_player_code.tolist() == [12345]
    assert labels.season_position_type.tolist() == [2]
    assert labels.available_at.isna().all()
    with sqlite3.connect(db) as con:
        con.execute('UPDATE player_gameweek SET total_points=5')
    with pytest.raises(ValueError, match='canonical label differences'):
        build_labels(root, db)


def test_extended_source_selection_keeps_match_and_season_granularity():
    assert raw.select(raw.REPOS[2], 'pl_stats/Arsenal_3/players_match_stats/2009-10_players_match_stats.csv')
    assert raw.select(raw.REPOS[3], 'data/2025/csv/gameweeks.csv')
    assert not raw.select(raw.REPOS[2], 'fpl_scraper/fpl/client.py')


def test_2014_reconciles_double_gameweek_without_backfilling_final_club():
    from experiments.data_ground_truth.historical_2014 import reconcile_2014
    weekly = pd.DataFrame([
        dict(id=1, name='Example', pos='Defender', team='Chelsea', pts=4, value=5, pct=10,
             date='17 May 15:00', gw=37, opp='CRY(H) 1-0', mins=90, gw_pts=2),
        dict(id=1, name='Example', pos='Defender', team='Chelsea', pts=4, value=5, pct=10,
             date='20 May 19:45', gw=37, opp='QPR(H) 1-0', mins=90, gw_pts=2),
    ])
    players = pd.DataFrame([dict(id=1, pts=4)])
    fixtures = pd.DataFrame([
        dict(matchId=100, kickoff='2015-05-17 15:00:00', home_team_id=3, away_team_id=31),
        dict(matchId=101, kickoff='2015-05-20 19:45:00', home_team_id=3, away_team_id=52),
    ])
    labels, report = reconcile_2014(weekly, players, fixtures)
    assert report['fixtures'] == 2
    assert report['double_gameweek_extra_rows'] == 1
    assert labels.match_team_code.tolist() == [3, 3]
    assert labels.final_season_team.tolist() == ['Chelsea', 'Chelsea']
    assert 'pts' not in labels
    assert labels.available_at.isna().all()
    assert not labels.eligible_predeadline.any()
    with pytest.raises(ValueError, match='season total'):
        reconcile_2014(weekly, players.assign(pts=5), fixtures)
    with pytest.raises(ValueError, match='ambiguous fixture'):
        reconcile_2014(weekly, players, pd.concat([fixtures, fixtures]))
    with pytest.raises(ValueError, match='unresolved fixtures'):
        reconcile_2014(weekly, players, fixtures.iloc[:1])


def test_archive_crosswalk_resolves_namespaces_without_assuming_equal_rounds():
    from experiments.data_ground_truth.crosswalk import fixture_crosswalk
    players = pd.DataFrame([dict(matchId=100,venue='Home',team_id=3),dict(matchId=100,venue='Away',team_id=31)])
    events = pd.DataFrame([dict(matchId=900,home_team_id=3,away_team_id=31,kickoff='2014-08-16 17:30:00')])
    linked=fixture_crosswalk(players,events)
    assert linked.matchId_players.tolist()==[100]
    assert linked.matchId_events.tolist()==[900]
    with pytest.raises(ValueError,match='ambiguous club pair'):
        fixture_crosswalk(players,pd.concat([events,events.assign(matchId=901)]))
    with pytest.raises(ValueError,match='missing match participant'):
        fixture_crosswalk(players.iloc[:1],events)
    with pytest.raises(ValueError,match='unresolved fixture'):
        fixture_crosswalk(players,events.assign(away_team_id=8))


def test_historical_identity_requires_unique_code_and_multiple_witnesses():
    from experiments.data_ground_truth.identity_2014 import resolve
    labels=pd.DataFrame([dict(id=1,name='Davies',pos='Defender',matchId=m,match_team_code=3,mins=68,gw_pts=2) for m in [1,2]])
    observations=pd.DataFrame([dict(matchId_events=m,team_id=3,official_player_code=10,minutesPlayed=69,playerName='Ben Davies',position='D') for m in [1,2]])
    linked,unresolved,evidence,report=resolve(labels,observations)
    assert report['resolved_players']==1
    assert report['minutes_disagreement_witness_rows']==2
    assert linked.mins.tolist()==[68,68]
    assert unresolved.empty
    assert evidence.matching_fixtures.tolist()==[2]
    assert resolve(labels.iloc[:1],observations)[3]['resolved_players']==0
    ambiguous=pd.concat([observations,observations.assign(official_player_code=11)])
    assert resolve(labels,ambiguous)[3]['resolved_players']==0
    assert resolve(labels,observations.assign(team_id=8))[3]['resolved_players']==0


def test_training_quarantines_only_verified_postponement_zeros():
    from experiments.data_ground_truth.training_dataset import quarantine_postponed
    frame=pd.DataFrame([
        dict(element=1,fixture=275,gw=29,minutes=0,total_points=0,kickoff_time='2020-03-11T19:30:00Z'),
        dict(element=1,fixture=275,gw=39,minutes=90,total_points=6,kickoff_time='2020-06-17T19:15:00Z'),
    ])
    fixtures=pd.DataFrame([dict(id=275,event=39,finished=True,kickoff_time='2020-06-17T19:15:00Z')])
    kept,excluded=quarantine_postponed(frame,fixtures)
    assert kept.gw.tolist()==[39]
    assert excluded.gw.tolist()==[29]
    with pytest.raises(ValueError,match='finished fixture'):
        quarantine_postponed(frame,fixtures.assign(finished=False))
    with pytest.raises(ValueError,match='actual observation'):
        quarantine_postponed(frame,fixtures.assign(event=38))
    changed=frame.copy();changed.loc[0,'total_points']=1
    with pytest.raises(ValueError,match='conflicting'):
        quarantine_postponed(changed,fixtures)
    assert len(quarantine_postponed(frame.iloc[1:],fixtures)[0])==1


def test_training_package_reproducibility_splits_and_integrity(tmp_path):
    from experiments.data_ground_truth.training_dataset import build, load_partition, verify
    recent=tmp_path/'recent';old=tmp_path/'old';out=tmp_path/'packages'
    (recent/'labels').mkdir(parents=True);(old/'identity').mkdir(parents=True)
    seasons={}
    for season in ['2023-24','2024-25','2025-26']:
        data=pd.DataFrame([dict(element=1,fixture=2,gw=1,minutes=90,total_points=4,
            official_player_code=123,kickoff_time='2025-08-01T15:00:00Z',final_season_value=99)]).to_csv(index=False).encode()
        (recent/'labels'/f'{season}.csv').write_bytes(data)
        seasons[season]={'artifact_sha256':raw.digest(data)}
    (recent/'labels-manifest.json').write_text(json.dumps({'seasons':seasons}))
    (recent/'manifest.json').write_text(json.dumps({'records':[]}))
    data=pd.DataFrame([dict(id=1,matchId=2,gw=1,mins=0,gw_pts=0,official_player_code=None,
        match_local_time='2014-08-16 17:30:00',final_season_value=99)]).to_csv(index=False).encode()
    (old/'identity/labels.csv').write_bytes(data)
    (old/'identity/report.json').write_text(json.dumps({'labels_sha256':raw.digest(data)}))
    package=build(recent,old,out)
    assert build(recent,old,out)==package
    assert verify(package)['rows']==4
    train=load_partition(package,'train')
    assert set(train.season)=={'2014-15','2023-24'}
    assert set(load_partition(package,'evaluation').season)=={'2025-26'}
    assert 'fpl:2014-15:1' in set(train.identity_key)
    assert 'final_season_value' not in train
    assert train.available_at.isna().all()
    assert not train.eligible_predeadline.any()
    artifact=package/'2025-26.csv.gz';original=artifact.read_bytes();artifact.write_bytes(original+b'changed')
    with pytest.raises(ValueError,match='hash mismatch'):
        load_partition(package,'train')
    artifact.write_bytes(original)
    manifest=json.loads((package/'manifest.json').read_text());manifest['rows']=99
    (package/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='manifest identity mismatch'):
        verify(package)


def test_snapshot_identity_enrichment_requires_matching_labels_and_unique_codes():
    from experiments.data_ground_truth.snapshots import enrich_identity, unpack
    labels=pd.DataFrame([dict(id=1,matchId=100,gw=1,mins=90,gw_pts=6,official_player_code=None)])
    snapshot=labels.assign(official_player_code=123)
    enriched,report=enrich_identity(labels,snapshot)
    assert enriched.official_player_code.tolist()==[123]
    assert report['added_players']==1
    with pytest.raises(ValueError,match='ground truth disagreement'):
        enrich_identity(labels,snapshot.assign(gw_pts=5))
    with pytest.raises(ValueError,match='conflicting snapshot identity'):
        enrich_identity(labels.assign(official_player_code=124),snapshot)
    collision=pd.concat([labels,labels.assign(id=2,official_player_code=123)])
    with pytest.raises(ValueError,match='cross-source identity collision'):
        enrich_identity(collision,snapshot)
    player=dict(id=1,total_points=6,code=123,web_name='Example',fixture_history="{'all': [['bad schema']]}")
    with pytest.raises(ValueError,match='unknown snapshot history schema'):
        unpack([player])


def test_partial_snapshot_reconciliation_preserves_season_and_missing_fixtures():
    from experiments.data_ground_truth.historical_2014 import reconcile_2014
    weekly=pd.DataFrame([dict(id=1,gw=1,date='08 Aug 15:00',opp='NOR(A) 3-1',mins=90,gw_pts=6)])
    players=pd.DataFrame([dict(id=1,pts=6)])
    fixtures=pd.DataFrame([
        dict(matchId=100,kickoff='2015-08-08 15:00:00',home_team_id=45,away_team_id=31),
        dict(matchId=101,kickoff='2016-05-15 15:00:00',home_team_id=31,away_team_id=45),
    ])
    labels,report=reconcile_2014(weekly,players,fixtures,season_start=2015,opponent_codes={'NOR':45})
    assert labels.season.tolist()==['2015-16']
    assert labels.match_team_code.tolist()==[31]
    assert report['missing_fixture_ids']==[101]
