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
    history=tmp_path/'2015';history.mkdir()
    data=pd.DataFrame([dict(id=1,matchId=i+1,gw=i//10+1,mins=0,gw_pts=0,
        official_player_code=123,match_local_time='2015-08-08 15:00:00') for i in range(380)]).to_csv(index=False).encode()
    (history/'labels.csv').write_bytes(data)
    quality=dict(fixtures=380,rows=380,missing_fixture_ids=[],season_points_disagreements=0,labels_sha256=raw.digest(data))
    (history/'report.json').write_text(json.dumps(quality))
    expanded=build(recent,old,out,season_2015_root=history)
    assert '2015-16' in set(load_partition(expanded,'train').season)
    assert verify(expanded)['missing_complete_seasons']==[]
    (history/'report.json').write_text(json.dumps(quality|{'rows':381}))
    with pytest.raises(ValueError,match='contradict coverage report'):
        build(recent,old,out,season_2015_root=history)
    for season in seasons:
        frame=pd.read_csv(recent/'labels'/f'{season}.csv').assign(season_position_type=2)
        if season=='2024-25':
            manager=frame.iloc[:1].assign(element=2,official_player_code=100000123,season_position_type=5,minutes=0,total_points=9,mng_win=1)
            frame=pd.concat([frame,manager],ignore_index=True)
        data=frame.to_csv(index=False).encode();(recent/'labels'/f'{season}.csv').write_bytes(data)
        seasons[season]={'artifact_sha256':raw.digest(data)}
    (recent/'labels-manifest.json').write_text(json.dumps({'seasons':seasons}))
    typed=build(recent,old,out,separate_managers=True)
    typed_manifest=verify(typed)
    assert typed_manifest['version']=='fpl-labels-v5' and typed_manifest['rows']==4
    assert typed_manifest['manager_rows']==1
    validation=load_partition(typed,'validation')
    assert validation.element.tolist()==[1] and validation.entity_type.tolist()==['player']
    managers=pd.read_csv(typed/typed_manifest['manager_partitions'][0]['file'],compression='gzip')
    assert managers.identity_key.tolist()==['fpl_manager:2024-25:2']
    assert managers.total_points.tolist()==[9] and managers.mng_win.tolist()==[1]
    assert not managers.eligible_player_training.any()
    assert 'official_player_code' not in managers and 'minutes' not in managers
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


def test_complete_2015_requires_all_fixtures_and_reconciled_components():
    from datetime import datetime, timedelta
    from experiments.data_ground_truth.historical_2014 import OPPONENT_CODES
    from experiments.data_ground_truth.historical_2015 import reconcile
    codes=OPPONENT_CODES.copy()
    for code in ['BUR','HUL','QPR']:
        del codes[code]
    codes.update(BOU=91,NOR=45,WAT=57)
    fixtures=[];players=[];fixture_id=0
    for home,home_id in codes.items():
        history=[]
        for away,away_id in codes.items():
            if home==away:
                continue
            gw=fixture_id//10+1
            kickoff=datetime(2015,8,8,15)+timedelta(weeks=gw-1,hours=fixture_id%10)
            fixture_id+=1
            fixtures.append(dict(matchId=fixture_id,kickoff=kickoff.isoformat(),home_team_id=home_id,away_team_id=away_id))
            history.append([kickoff.strftime('%d %b %H:%M'),gw,f'{away}(H) 0-0',90]+[0]*15+[2])
        player=dict(id=home_id,code=home_id+1000,web_name=home,fixture_history={'all':history},total_points=38,minutes=1710)
        for column in ['goals_scored','assists','clean_sheets','goals_conceded','own_goals','penalties_saved','penalties_missed','yellow_cards','red_cards','saves','bonus','bps']:
            player[column]=0
        players.append(player)
    frame,report=reconcile(players,pd.DataFrame(fixtures))
    assert len(frame)==380
    assert not any(report['component_total_disagreements'].values())
    assert report['missing_fixture_ids']==[]
    with pytest.raises(ValueError,match='unresolved fixtures'):
        reconcile(players,pd.DataFrame(fixtures).iloc[:-1])
    players[0]['minutes']+=1
    with pytest.raises(ValueError,match='component total disagreement'):
        reconcile(players,pd.DataFrame(fixtures))


def test_registry_uses_full_names_and_preserves_missing_minutes():
    from experiments.data_ground_truth.identity_registry import link_archive
    observations=pd.DataFrame([
        dict(team_id=1,playerId=10,playerName='Filip Đuričić',official_player_code=None,minutesPlayed=9),
        dict(team_id=1,playerId=10,playerName='Filip Đuričić',official_player_code=None,minutesPlayed=None),
        dict(team_id=1,playerId=11,playerName='Luke Daniels',official_player_code=20,minutesPlayed=0),
    ])
    squads=pd.DataFrame([dict(team_id=1,playerId=30,displayName='Filip Djuricic'),
        dict(team_id=1,playerId=40,displayName='Donervon Daniels')])
    linked,report=link_archive(observations,squads)
    assert report['added_identity_rows']==2
    assert linked.official_player_code.tolist()==[30,30,20]
    assert linked.minutesPlayed.isna().sum()==1
    assert not linked.iloc[1].eligible_observed_minutes_label
    with pytest.raises(ValueError,match='registry code conflict'):
        link_archive(observations.fillna({'official_player_code':99}),squads)


def test_identity_requires_every_played_fixture_and_corroboration():
    from experiments.data_ground_truth.identity_registry import reconcile_labels
    labels=pd.DataFrame([dict(id=1,name='Example',matchId=m,match_team_code=3,mins=1,gw_pts=1,official_player_code=None) for m in [100,101]])
    obs=pd.DataFrame([dict(matchId_events=m,team_id=3,playerName='Full Example',minutesPlayed=1,official_player_code=123,registry_code=123) for m in [100,101]])
    old=pd.DataFrame(columns=['id'])
    linked,report=reconcile_labels(labels,obs,old,[])
    assert report['added_players']==1
    assert linked.official_player_code.tolist()==[123,123]
    assert reconcile_labels(labels,obs.iloc[:1],old,[])[1]['added_players']==0
    assert reconcile_labels(labels,obs.assign(registry_code=None),old,[])[1]['added_players']==0
    assert reconcile_labels(labels.assign(mins=0),obs,old,[])[1]['added_players']==0
    ambiguous=pd.concat([obs,obs.assign(official_player_code=124,registry_code=124)])
    assert reconcile_labels(labels,ambiguous,old,[])[1]['added_players']==0


def test_historical_code_alias_requires_direct_fullname_and_prior_totals():
    from experiments.data_ground_truth.identity_registry import reconcile_labels
    from experiments.data_ground_truth.training_dataset import normalize
    labels=pd.DataFrame([dict(id=1,name='Brown',matchId=100,match_team_code=3,gw=1,mins=12,gw_pts=1,
        official_player_code=10,match_local_time='2014-08-16 15:00:00')])
    obs=pd.DataFrame([dict(matchId_events=100,team_id=3,playerName='Isaiah Brown',minutesPlayed=11,official_player_code=20,registry_code=20)])
    old=pd.DataFrame([dict(id=1,first_name='Isaiah',second_name='Brown',code=10)])
    player=dict(code=20,first_name='Isaiah',second_name='Brown',web_name='Brown',team_code=3,season_history=[['2014/15',12,1]])
    linked,report=reconcile_labels(labels,obs,old,[player])
    assert report['aliases'][0]['source_code']==10
    normalized=normalize(linked,'2014-15',True)
    assert normalized.identity_key.tolist()==['opta:20']
    assert normalized.source_official_player_code.tolist()==[10]
    assert normalized.minutes.tolist()==[12]
    for bad in [player|{'first_name':'Other'},player|{'season_history':[['2014/15',11,1]]},player|{'team_code':4}]:
        with pytest.raises(ValueError,match='unverified historical code alias'):
            reconcile_labels(labels,obs,old,[bad])
    with pytest.raises(ValueError,match='without old metadata'):
        reconcile_labels(labels,obs,old.iloc[:0],[player])
    no_registry=obs.assign(registry_code=None)
    assert reconcile_labels(labels, no_registry, old, [player])[1]['aliases']


def test_acquire_reuses_pinned_inventory_and_rejects_wrong_revision(tmp_path,monkeypatch):
    pins={raw.REPOS[8]:'a'*40};inventory=tmp_path/'inventories'/('sjp4-'+'a'*40+'.json')
    inventory.parent.mkdir(parents=True)
    tree=dict(sha='a'*40,truncated=False,tree=[dict(type='blob',path='README.md')])
    inventory.write_text(json.dumps(tree))
    calls=[]
    def get(url):
        calls.append(url)
        assert 'api.github.com' not in url
        return b'public archive documentation'
    monkeypatch.setattr(raw,'_get',get)
    result=raw.acquire(tmp_path,pins)
    assert len(result['records'])==1
    assert len(calls)==1
    inventory.write_text(json.dumps(tree|{'sha':'b'*40}))
    with pytest.raises(ValueError,match='mismatched source inventory'):
        raw.acquire(tmp_path,pins)
    assert not raw.select(raw.REPOS[8],'Differential/Database/DiffMoi_device.db3')


def test_archive_audit_does_not_count_future_placeholders_as_labels(tmp_path):
    import sqlite3
    from experiments.data_ground_truth.differential_audit import read_tables,quality
    db=tmp_path/'archive.db3'
    matches=pd.DataFrame([
        dict(season=11,player_fpl_id=1,fixture_id=100,gameweek=37,minutes=90,total=2),
        dict(season=11,player_fpl_id=1,fixture_id=101,gameweek=38,minutes=None,total=None),
    ])
    metadata=pd.DataFrame([dict(season=11,fpl_id=1,player_id=900,minutes=90,points=2)])
    fixtures=pd.DataFrame([dict(season=11,_id=100),dict(season=11,_id=101)])
    with sqlite3.connect(db) as con:
        for name,frame in [('player_match',matches),('player_season',metadata),('fixture',fixtures)]:
            frame.to_sql(name,con,index=False)
    before=raw.digest(db.read_bytes());tables=read_tables(db);report=quality(tables)['11']
    assert raw.digest(db.read_bytes())==before
    assert report['referenced_gameweeks']==[37,38]
    assert report['gameweeks_with_both_labels']==[37]
    assert report['missing_minutes']==report['missing_points']==1
    assert report['player_total_disagreements']==0
    assert report['source_player_key']=='player_fpl_id'
    assert report['status']=='unreconciled_archive_not_full_season_ground_truth'
    tables['player_season']['points']=3
    assert quality(tables)['11']['player_total_disagreements']==1


def test_sql_literals_preserve_quoted_comments_and_never_execute():
    from experiments.data_ground_truth.sql_archive import extract,literals
    text="""-- archived data
    INSERT INTO player (_id,name) VALUES (1,'O''Brien;\n--literal');
    UPDATE player SET name=NULL; DELETE FROM player;
    """
    tables,ignored=extract(text)
    assert tables['player'].name.tolist()==["O'Brien;\n--literal"]
    assert ignored=={'update':1,'delete':1}
    assert literals('0,NULL,-2,1.5')==[0,None,-2,1.5]
    for bad in ["load_extension('anything')",'1e999','1,']:
        with pytest.raises(ValueError):literals(bad)
    with pytest.raises(ValueError,match='unsupported SQL insert'):
        extract('INSERT INTO player SELECT * FROM elsewhere;')
    with pytest.raises(ValueError,match='unterminated'):
        extract("INSERT INTO player (name) VALUES ('broken);")


def test_archive_detects_missing_positive_appearance_despite_matching_present_totals():
    from experiments.data_ground_truth.differential_audit import quality
    tables=dict(player_match=pd.DataFrame([dict(season=11,player_fpl_id=1,fixture_id=10,gameweek=1,minutes=90,total=2)]),
        player_season=pd.DataFrame([dict(season=11,fpl_id=1,minutes=90,points=2),dict(season=11,fpl_id=2,minutes=9,points=1)]),
        fixture=pd.DataFrame([dict(season=11,_id=10)]))
    report=quality(tables)['11']
    assert report['player_total_disagreements']==0
    assert report['positive_minutes_players_without_match_rows']==1
    assert report['missing_appearance_player_ids']==[2]


def test_bson_audit_quarantines_conflicts_without_repairing_identity():
    from experiments.data_ground_truth.bson_archive import reconcile
    import copy
    player=dict(id=1,code=100,total_points=2,fixture_history=[dict(date='01 Jan 15:00',gameweek=1,
        opponent_result='ARS(H) 1-0',mins_played=90,points=2)])
    reference=pd.DataFrame([dict(id=1,date='01 Jan 15:00',opp='ARS(H) 1-0',matchId=10,mins=90,gw_pts=2,gw=1,official_player_code=100)])
    good=reconcile([player],reference)
    assert good['corroborated_rows']==1
    assert good['quarantined_conflict_rows']==0
    duplicate=player|{'id':2}
    report=reconcile([player,duplicate],reference)
    assert report['corroborated_rows']==0
    assert all('ambiguous_identity' in r['reasons'] for r in report['quarantined_player_records'])
    bad=copy.deepcopy(player);bad['fixture_history'][0]['points']=3
    report=reconcile([bad],reference)
    assert report['quarantined_conflict_rows']==1
    assert 'gw_pts_disagreement' in report['quarantined_player_records'][0]['reasons']
    assert not report['eligible_training']
    unmatched=copy.deepcopy(player);unmatched['fixture_history'][0]['date']='02 Jan 15:00'
    assert 'unmatched_observations' in reconcile([unmatched],reference)['quarantined_player_records'][0]['reasons']


def test_appearance_coverage_checks_namespaces_dates_and_preserves_unknowns():
    from experiments.data_ground_truth.appearance_coverage import compare
    matches=pd.DataFrame([dict(season=11,player_fpl_id=1,fixture_id=10,is_home=1,opp_team_id=2,minutes=1)])
    fixtures=pd.DataFrame([dict(season=11,_id=10,team_home_id=1,team_away_id=2,datetime=1281783600)])
    teams=pd.DataFrame([dict(_id=1,name='Arsenal'),dict(_id=2,name='Aston Villa')])
    players=pd.DataFrame([dict(_id=1,name='Smith')])
    obs=pd.DataFrame([dict(season='2010-11',matchId_events=999,team_id=3,team='Arsenal',playerId=20,playerName='John Smith',minutesPlayed=None),
        dict(season='2010-11',matchId_events=999,team_id=7,team='Aston_Villa',playerId=30,playerName='Other Player',minutesPlayed=90)])
    reference=pd.DataFrame([dict(home_team_id=3,away_team_id=7,matchId_events=999,kickoff='2010-08-14 15:00:00')])
    coverage,candidates,report=compare(matches,fixtures,teams,players,obs,reference)
    assert report['fixtures']==1
    assert report['sport_unknown_minute_rows']==1
    assert candidates.candidate_native_player_id.tolist()==[20]
    assert not candidates.eligible_identity.any()
    assert not coverage.appearance_count_agrees.any()
    ambiguous=pd.concat([obs,obs.iloc[:1].assign(playerId=21,playerName='James Smith')])
    assert compare(matches,fixtures,teams,players,ambiguous,reference)[2]['unique_candidate_players']==0
    with pytest.raises(ValueError,match='fixture date disagreement'):
        compare(matches,fixtures,teams,players,obs,reference.assign(kickoff='2010-08-15 15:00:00'))
    with pytest.raises(ValueError,match='opponent disagreement'):
        compare(matches.assign(opp_team_id=1),fixtures,teams,players,obs,reference)
    with pytest.raises(ValueError,match='ambiguous fixture pair'):
        compare(matches,fixtures,teams,players,obs,pd.concat([reference,reference]))


def test_native_identity_requires_repeated_fullname_witnesses_and_preserves_unknown_minutes():
    from experiments.data_ground_truth.native_identity import propagate
    rows=[dict(season='2010-11',playerId=1,playerName='John Smith',matchId_events=m,
        official_player_code=20,source_official_player_code=20,minutesPlayed=90) for m in [100,101]]
    rows+=[dict(season='2011-12',playerId=1,playerName=name,matchId_events=200,
        official_player_code=None,source_official_player_code=None,minutesPlayed=None) for name in ['John Smith','James Smith']]
    frame=pd.DataFrame(rows)
    linked,evidence=propagate(frame)
    assert linked.loc[2,'official_player_code']==20
    assert pd.isna(linked.loc[3,'official_player_code'])
    assert pd.isna(linked.loc[2,'source_official_player_code'])
    assert pd.isna(linked.loc[2,'minutesPlayed'])
    assert not linked.loc[2,'eligible_observed_minutes_label']
    assert not linked.eligible_predeadline.any()
    assert evidence[0]['witness_fixtures']==[['2010-11',100],['2010-11',101]]
    single=pd.concat([frame.iloc[:1],frame.iloc[:1],frame.iloc[2:]],ignore_index=True)
    assert not propagate(single)[0].native_identity_recovered.any()
    conflict=frame.copy();conflict.loc[1,'official_player_code']=21
    with pytest.raises(ValueError,match='namespace code conflict'):propagate(conflict)
    # A different native ID with the same name cannot donate its identity.
    renamed=frame.copy();renamed.loc[2:,'playerId']=2
    assert not propagate(renamed)[0].native_identity_recovered.any()


def test_historical_identity_requires_every_positive_fixture_and_preserves_fpl_labels():
    from experiments.data_ground_truth.historical_identity import resolve,name_matches
    assert name_matches('Young L','Luke Young')
    assert not name_matches('Young L','Ashley Young')
    assert name_matches('Diouf EH','El Hadji Diouf')
    assert not name_matches('Diouf EH','Mame Biram Diouf')
    assert not name_matches('Hammil','Adam Hammill')
    appearances=pd.DataFrame([dict(player_fpl_id=1,fixture_id=m,matchId_events=m+100,team_id=3,minutes=26,total=1) for m in [1,2]])
    players=pd.DataFrame([dict(_id=1,name='Smith')])
    observations=pd.DataFrame([dict(matchId_events=m+100,team_id=3,playerId=40,playerName='John Smith',minutesPlayed=25,official_player_code=20) for m in [1,2]])
    linked,evidence,report=resolve(appearances,players,observations)
    assert report['verified_players']==1 and report['verified_rows']==2
    assert linked.official_player_code.tolist()==[20,20]
    assert linked.minutes.tolist()==[26,26]
    assert report['source_outcomes_preserved']
    assert not linked.eligible_training.any() and not linked.eligible_predeadline.any()
    assert evidence[0]['fixtures']==[101,102]
    for bad in [observations.iloc[:1],observations.assign(minutesPlayed=None),observations.assign(minutesPlayed=0)]:
        assert resolve(appearances,players,bad)[2]['verified_rows']==0
    assert resolve(appearances.iloc[:1],players,observations)[2]['verified_rows']==0
    ambiguous=pd.concat([observations,observations.assign(playerId=41,playerName='James Smith',official_player_code=21)])
    assert resolve(appearances,players,ambiguous)[2]['verified_rows']==0
    duplicate=pd.concat([appearances,appearances.assign(player_fpl_id=2)],ignore_index=True)
    with pytest.raises(ValueError,match='cross-FPL identity collision'):
        resolve(duplicate,pd.concat([players,players.assign(_id=2)]),observations)


def test_later_fpl_history_can_corroborate_single_appearance_but_not_wrong_fullname():
    from experiments.data_ground_truth.historical_identity import resolve
    a=pd.DataFrame([dict(player_fpl_id=1,fixture_id=10,matchId_events=100,team_id=3,minutes=1,total=1)])
    p=pd.DataFrame([dict(_id=1,name='Smith')])
    o=pd.DataFrame([dict(matchId_events=100,team_id=3,playerId=30,playerName='John Smith',minutesPlayed=None,official_player_code=20)])
    later=dict(code=20,first_name='John',second_name='Smith',season_history=[['2010/11',1,1]])
    linked,evidence,report=resolve(a,p,o,[later])
    assert report['verified_rows']==1
    assert evidence[0]['corroborated_by_later_fpl_season_totals']
    for bad in [later|{'first_name':'James'},later|{'season_history':[['2010/11',2,1]]},later|{'code':21}]:
        assert resolve(a,p,o,[bad])[2]['verified_rows']==0
    assert resolve(a,p,o.assign(minutesPlayed=1),[later|{'first_name':'James'}])[2]['verified_rows']==0


def test_database_overlap_does_not_invent_labels_from_complementary_nulls():
    from experiments.data_ground_truth.season_evidence import compare_versions
    a=pd.DataFrame([dict(season=12,player_player_id=1,fixture_id=10,minutes=90,total=None)])
    b=a.assign(minutes=None,total=2)
    result=compare_versions({'a':a,'b':b})['seasons']['12']
    assert result['union_keys']==1
    assert result['union_observed_keys']==0
    assert result['additional_observed_keys_over_best']==0
    c=a.assign(total=2)
    result=compare_versions({'a':c,'b':c.copy()})['seasons']['12']
    assert result['union_observed_keys']==1 and result['conflicting_keys']==0
    assert compare_versions({'a':c,'b':c.assign(total=3)})['seasons']['12']['conflicting_keys']==1
    with pytest.raises(ValueError,match='duplicate archived appearance'):
        compare_versions({'a':pd.concat([c,c])})


def test_season_histories_are_aggregates_not_fixture_eligibility():
    from experiments.data_ground_truth.season_evidence import extract_histories,reconcile_totals
    h=['2014/15',90]+[0]*14+[2]
    player=dict(code=20,first_name='John',second_name='Smith',season_history=[h],source_sha256='a'*64)
    frame=extract_histories([player])
    assert frame.observation_unit.tolist()==['player_season']
    assert not frame.eligible_training.any() and not frame.eligible_predeadline.any()
    labels=pd.DataFrame([dict(official_player_code=20,mins=90,gw_pts=2)])
    assert reconcile_totals(frame,labels)['matched_players']==1
    with pytest.raises(ValueError,match='total disagreement'):
        reconcile_totals(frame,labels.assign(gw_pts=3))
    with pytest.raises(ValueError,match='duplicate season identity'):extract_histories([player,player])
    with pytest.raises(ValueError,match='schema'):extract_histories([player|{'season_history':[h[:-1]]}])
    with pytest.raises(ValueError,match='historical season'):
        extract_histories([player|{'season_history':[['2014/16']+h[1:]]}])
    unknown=frame.assign(official_player_code=21,minutes=0,points=0)
    result=reconcile_totals(unknown,labels)
    assert result['unmatched_players']==1 and result['unmatched_positive_minutes']==0


def test_history_csv_validation_and_conflict_consensus():
    from experiments.data_ground_truth.history_consensus import parse,consensus
    record=dict(path='data/2016-17/players/Example/history.csv',sha256='a'*64)
    data=b'element_code,season_name,minutes,total_points\n20,2010/11,90,2\n'
    frame,status=parse(data,record)
    assert status=='parsed' and frame.minutes.tolist()==[90]
    duplicate=frame.assign(source_sha256='b'*64)
    accepted,rejected=consensus(pd.concat([frame,duplicate]))
    assert len(accepted)==1 and rejected.empty
    assert accepted.witness_records.tolist()==[2]
    assert not accepted.eligible_predeadline.any() and not accepted.population_complete.any()
    accepted,rejected=consensus(pd.concat([frame,duplicate.assign(points=3)]))
    assert accepted.empty and len(rejected)==2
    assert parse(b'',record)[1]=='empty_file'
    with pytest.raises(ValueError,match='chronology'):
        parse(data.replace(b'2010/11',b'2018/19'),record)
    with pytest.raises(ValueError,match='noninteger'):
        parse(data.replace(b',90,',b',90.5,'),record)
    with pytest.raises(ValueError,match='duplicate'):
        parse(data+b'20,2010/11,90,2\n',record)


def test_player_history_acquisition_is_pinned_filtered_and_resumable(tmp_path,monkeypatch):
    from experiments.data_ground_truth.history_archive import acquire
    revision='a'*40;inventory=tmp_path/'tree.json'
    inventory.write_text(json.dumps(dict(sha=revision,truncated=False,tree=[
        dict(type='blob',path='data/2016-17/players/Example/history.csv'),
        dict(type='blob',path='data/2026-27/players/Example/history.csv'),
        dict(type='blob',path='data/2016-17/gws/merged_gw.csv')])))
    calls=[]
    def get(url):calls.append(url);return b'element_code,season_name,minutes,total_points\n'
    monkeypatch.setattr(raw,'_get',get)
    result=acquire(tmp_path/'raw',inventory,revision)
    assert result['expected_files']==1 and len(result['records'])==1
    assert acquire(tmp_path/'raw',inventory,revision)['records']==result['records']
    assert len(calls)==1
    with pytest.raises(ValueError,match='inventory'):acquire(tmp_path/'raw',inventory,'b'*40)


def test_history_snapshot_can_select_current_folder_without_personal_team_data(tmp_path,monkeypatch):
    from experiments.data_ground_truth.history_archive import acquire
    inventory=tmp_path/'tree.json';revision='a'*40
    inventory.write_text(json.dumps(dict(sha=revision,truncated=False,tree=[
        dict(type='blob',path='data/2026-27/players/Example/history.csv'),
        dict(type='blob',path='team_123/history.csv'),
        dict(type='blob',path='data/2025-26/players/Example/history.csv')])))
    monkeypatch.setattr(raw,'_get',lambda url:b'element_code,season_name,minutes,total_points\n')
    report=acquire(tmp_path/'raw',inventory,revision,'2026-27')
    assert report['expected_files']==1
    assert report['records'][0]['path']=='data/2026-27/players/Example/history.csv'
    with pytest.raises(ValueError,match='snapshot season'):acquire(tmp_path/'raw',inventory,revision,'2026-28')


def test_history_extension_preserves_conflicting_prior_witnesses_and_excludes_open_season(tmp_path):
    from experiments.data_ground_truth.history_consensus import build
    prior=tmp_path/'prior';prior.mkdir()
    f=pd.DataFrame([dict(season='2025/26',official_player_code=20,minutes=90,points=2,source_sha256=s*64,source_path='earlier') for s in ['a','b']])
    f.to_csv(prior/'source_observations.csv',index=False)
    prior_sha=raw.digest((prior/'source_observations.csv').read_bytes())
    (prior/'report.json').write_text(json.dumps(dict(version='history-consensus-v1',artifacts={'source_observations.csv':prior_sha})))
    root=tmp_path/'raw';(root/'objects').mkdir(parents=True)
    records=[]
    for name,data in [('One',b'element_code,season_name,minutes,total_points\n20,2025/26,90,3\n'),
                      ('Two',b'element_code,season_name,minutes,total_points\n30,2025/26,90,2\n30,2026/27,1,1\n')]:
        sha=raw.digest(data);(root/'objects'/sha).write_bytes(data)
        records.append(dict(path=f'data/2026-27/players/{name}/history.csv',sha256=sha))
    (root/'manifest.json').write_text(json.dumps(dict(records=records,errors=[],expected_files=2)))
    out=tmp_path/'out';report=build(root,prior,out,closed_through=2025)
    assert report['prior_unique_keys']==1 and report['prior_rows']==2
    assert report['conflicting_player_seasons']==1
    assert report['consensus_player_seasons']==1
    assert report['excluded_open_season_rows']==1
    assert report['additional_consensus_keys_over_prior']==1
    assert len(pd.read_csv(out/'conflicting_observations.csv'))==3
    assert raw.digest((prior/'source_observations.csv').read_bytes())==prior_sha
    assert pd.read_csv(out/'consensus_totals.csv').season.tolist()==['2025/26']


def test_season_reference_audit_separates_disagreement_from_missing_population():
    from experiments.data_ground_truth.history_reference import compare
    totals=pd.DataFrame([dict(season='2025/26',official_player_code=i,minutes=90,points=2) for i in [1,2]])
    reference=pd.DataFrame([dict(season='2025/26',official_player_code=i,minutes=90,points=3) for i in [1,3]])
    joined,report=compare(totals,reference)
    assert report['matched_players']==report['outcome_disagreements']==1
    assert report['seasons']['2025/26']['history_without_reference']==1
    assert report['seasons']['2025/26']['reference_without_history']==1
    assert joined.outcome_disagreement.sum()==1
    assert compare(totals.assign(season='2010/11'),reference)[1]['unsupported_history_rows']==2
    with pytest.raises(ValueError,match='ambiguous'):
        compare(pd.concat([totals,totals]),reference)


def test_label_repair_requires_exact_fixture_identity_and_final_component_totals():
    from experiments.data_ground_truth.label_repairs import repair_player
    original=pd.DataFrame([dict(element=1,fixture=10,gw=24,round=24,kickoff_time='2025-02-01T12:30:00Z',
        official_player_code=20,minutes=0,total_points=0,goals_conceded=0)])
    individual=pd.DataFrame([dict(element=1,fixture=10,round=24,kickoff_time='2025-02-01T12:30:00Z',
        minutes=17,total_points=1,goals_conceded=2)])
    metadata=pd.DataFrame([dict(id=1,code=20,minutes=17,total_points=1,goals_conceded=2)])
    repaired,changes=repair_player(original,individual,metadata,['goals_conceded'])
    assert repaired.minutes.tolist()==[17] and repaired.total_points.tolist()==[1]
    assert repaired.goals_conceded.tolist()==[2] and len(changes)==3
    assert original.minutes.tolist()==[0]
    with pytest.raises(ValueError,match='season total disagreement'):
        repair_player(original,individual.assign(minutes=18),metadata,['goals_conceded'])
    with pytest.raises(ValueError,match='code disagreement'):
        repair_player(original,individual,metadata.assign(code=21),['goals_conceded'])
    with pytest.raises(ValueError,match='fixture coverage'):
        repair_player(original,individual.assign(fixture=11),metadata,['goals_conceded'])
    with pytest.raises(ValueError,match='kickoff'):
        repair_player(original,individual.assign(kickoff_time='2025-02-02T12:30:00Z'),metadata,['goals_conceded'])
    with pytest.raises(ValueError,match='gameweek'):
        repair_player(original,individual.assign(round=25),metadata,['goals_conceded'])


def test_individual_audit_detects_cancelling_row_errors_even_when_totals_match():
    from experiments.data_ground_truth.individual_audit import compare_player
    from experiments.data_ground_truth.training_dataset import COMPONENTS
    rows=[dict(element=1,fixture=i,gw=i,official_player_code=20,event_time_utc=f'2025-01-0{i}T15:00:00Z',
        minutes=m,total_points=2,**{c:0 for c in COMPONENTS}) for i,m in [(1,10),(2,20)]]
    reference=pd.DataFrame(rows)
    individual=reference.rename(columns={'gw':'round','event_time_utc':'kickoff_time'}).assign(minutes=[11,19])
    metadata=pd.DataFrame([dict(id=1,code=20,element_type=2,minutes=30,total_points=4,**{c:0 for c in COMPONENTS})])
    report,differences=compare_player(individual,reference,metadata,pd.DataFrame())
    assert report['season_total_disagreements']==[]
    assert report['changed_rows']==report['changed_fields']==2
    assert {d['fixture'] for d in differences}=={1,2}
    missing=individual.iloc[:1]
    assert compare_player(missing,reference,metadata,pd.DataFrame())[0]['reference_only_rows']==1
    with pytest.raises(ValueError,match='identity disagreement'):
        compare_player(individual,reference,metadata.assign(code=21),pd.DataFrame())


def test_individual_acquisition_selects_gw_files_only(tmp_path,monkeypatch):
    from experiments.data_ground_truth.history_archive import acquire
    revision='a'*40;inventory=tmp_path/'tree.json'
    inventory.write_text(json.dumps(dict(sha=revision,truncated=False,tree=[dict(type='blob',path=p) for p in [
        'data/2025-26/players/Example/gw.csv','data/2025-26/players/Example/history.csv','team_123/gw.csv']])) )
    monkeypatch.setattr(raw,'_get',lambda url:b'element,fixture,minutes,total_points\n')
    report=acquire(tmp_path/'raw',inventory,revision,artifact='gw')
    assert report['expected_files']==1 and report['records'][0]['path'].endswith('/Example/gw.csv')
    with pytest.raises(ValueError,match='unsupported player artifact'):
        acquire(tmp_path/'raw',inventory,revision,artifact='../something')


def test_bootstrap_archive_preserves_naive_clock_and_validates_inventory(tmp_path,monkeypatch):
    from experiments.data_ground_truth.bootstrap_archive import acquire,claimed_time,PROVENANCE
    path='cache/2024/8/16/1100.json.xz';revision='b'*40
    assert claimed_time(path)=='2024-08-16T11:00:00'
    with pytest.raises(ValueError):claimed_time('cache/2024/2/30/1100.json.xz')
    with pytest.raises(ValueError):claimed_time('../2024/8/16/1100.json.xz')
    inventory=tmp_path/'inventory.json'
    tree=dict(sha=revision,truncated=False,tree=[dict(type='blob',path=p,size=3) for p in sorted(PROVENANCE|{path})])
    inventory.write_text(json.dumps(tree));monkeypatch.setattr(raw,'_get',lambda url:b'raw')
    result=acquire(tmp_path/'raw',inventory,revision)
    assert result['expected_snapshots']==1 and result['errors']==[]
    record=next(r for r in result['records'] if r['path']==path)
    assert record['source_timezone'] is None and record['available_at'] is None
    assert not record['eligible_predeadline']
    tree['truncated']=True;inventory.write_text(json.dumps(tree))
    with pytest.raises(ValueError,match='inventory'):acquire(tmp_path/'raw',inventory,revision)


def test_bootstrap_decoder_rejects_oversize_trailing_and_truncated_data():
    import lzma
    from experiments.data_ground_truth.bootstrap_audit import decode
    data=lzma.compress(b'{"test": true}')
    assert decode(data)=={'test':True}
    for payload,limit in [(data,3),(data+b'extra',100),(data[:-4],100)]:
        with pytest.raises(ValueError):decode(payload,limit)


def test_bootstrap_audit_keeps_nominal_deadlines_ineligible_and_nulls_unknown():
    import copy
    from experiments.data_ground_truth.bootstrap_audit import inspect
    snapshot=dict(elements=[dict(id=1,element_type=2,code=100,now_cost=45,news='',status='a'),
                            dict(id=2,element_type=5,now_cost=10)],
                  events=[dict(id=1,deadline_time='2024-08-16T17:30:00Z',finished=False)])
    row,candidates=inspect(snapshot,'cache/2024/8/16/1100.json.xz')
    assert row['season']=='2024-25' and row['players']==row['managers']==1
    assert row['fields']['now_cost']==dict(present=1,nonnull=1)
    assert row['fields']['chance_of_playing_next_round']==dict(present=0,nonnull=0)
    assert candidates[0]['nominal_hours_before']==6.5 and not candidates[0]['eligible_predeadline']
    assert inspect(snapshot,'cache/2024/8/16/1800.json.xz')[1]==[]
    duplicate=copy.deepcopy(snapshot);duplicate['elements'].append(duplicate['elements'][0])
    with pytest.raises(ValueError,match='duplicate'):inspect(duplicate,'cache/2024/8/16/1100.json.xz')


def test_bootstrap_report_retains_corrupt_snapshot_in_coverage_denominator(tmp_path):
    import lzma
    from experiments.data_ground_truth.bootstrap_audit import build
    source=tmp_path/'raw';(source/'objects').mkdir(parents=True)
    snapshot=dict(elements=[dict(id=1,element_type=2)],events=[dict(id=1,deadline_time='2024-08-16T17:30:00Z',finished=False)])
    data=lzma.compress(json.dumps(snapshot).encode());sha=raw.digest(data)
    (source/'objects'/sha).write_bytes(data)
    corrupt_sha='a'*64;(source/'objects'/corrupt_sha).write_bytes(b'corrupt')
    records=[dict(path='cache/2024/8/16/1100.json.xz',sha256=sha),
             dict(path='cache/2024/8/16/1200.json.xz',sha256=corrupt_sha)]
    (source/'manifest.json').write_text(json.dumps(dict(records=records,errors=[],expected_files=2,expected_snapshots=2)))
    out=tmp_path/'audit';report=build(source,out)
    assert report['snapshots']==2 and report['parsed_snapshots']==report['errors']==1
    assert report['verified_predeadline_snapshots']==0 and not report['eligible_predeadline']
    assert report['seasons']['2024-25']['nominal_deadlines_with_snapshot_within_48h']==[1]
    assert json.loads((out/'errors.json').read_text())[0]['sha256']==corrupt_sha
    assert all(raw.digest((out/name).read_bytes())==sha for name,sha in report['artifacts'].items())


def test_bootstrap_state_units_unknown_flags_and_identity_conflicts():
    from experiments.data_ground_truth.bootstrap_state import normalize
    e=dict(id=1,code=20,element_type=2,team=3,now_cost=45,status='a',selected_by_percent='12.3',
           chance_of_playing_next_round=None)
    row=normalize(e,{3:99},{1:20})
    assert row['price_tenths_gbp']==45 and row['price_gbp']=='4.5'
    assert row['ownership_percent']=='12.3' and row['snapshot_team_code']==99
    assert row['can_select'] is None and not row['can_select_present']
    assert row['chance_of_playing_next_round'] is None and row['chance_of_playing_next_round_present']
    explicit=normalize(dict(e,can_select=False,can_transact=True),{3:99},{1:20})
    assert explicit['can_select'] is False and explicit['can_select_present']
    assert not explicit['eligible_training'] and not explicit['eligible_predeadline']
    for bad in [dict(e,now_cost=True),dict(e,now_cost=4.5),dict(e,selected_by_percent='NaN'),
                dict(e,selected_by_percent='101'),dict(e,can_select='false'),dict(e,team=4)]:
        with pytest.raises(ValueError):normalize(bad,{3:99},{1:20})
    with pytest.raises(ValueError,match='code conflict'):normalize(e,{3:99},{1:21})
    assert normalize(e,{3:99},None)['reference_identity_status']=='reference_season_unavailable'
    assert normalize(dict(e,element_type=5),{3:99},{1:21})['reference_identity_status']=='manager_slot_not_player_identity'


def test_bootstrap_identity_tracks_variants_without_merging_slots_or_people():
    from experiments.data_ground_truth.bootstrap_identity import observe,summarize
    registry={}
    event=dict(id=1,deadline_time='2024-08-16T17:30:00Z')
    def record(day):return dict(path=f'cache/2024/8/{day}/1100.json.xz',sha256=str(day)*32)
    def element(eid,code,name='First',position=2):return dict(id=eid,code=code,first_name=name,second_name='Last',element_type=position,team=1)
    observe(registry,dict(events=[event],elements=[element(1,20),element(2,30,'Coach',5)]),record(16))
    observe(registry,dict(events=[event],elements=[element(1,21),element(2,30,'Replacement',5),element(3,20)]),record(17))
    entries,collisions=summarize(registry)
    assert entries[0]['code_count']==2 and entries[0]['name_count']==1
    assert entries[1]['code_count']==1 and entries[1]['name_count']==2 and entries[1]['entity_types']==[5]
    assert collisions==[dict(season='2024-25',code=20,elements=[1,3])]
    assert entries[0]['variants'][0]['first']['source_claimed_at']=='2024-08-16T11:00:00'
    assert entries[0]['variants'][0]['last']['source_claimed_at']=='2024-08-16T11:00:00'


def test_bootstrap_identity_rejects_a_snapshot_without_partial_witnesses():
    from experiments.data_ground_truth.bootstrap_identity import observe
    registry={}
    good=dict(id=1,code=20,first_name='A',second_name='B',element_type=2,team=1)
    snapshot=dict(events=[dict(id=1,deadline_time='2024-08-16T17:30:00Z')],
                  elements=[good,dict(good,id=2,code=False)])
    with pytest.raises(ValueError,match='identity integer'):
        observe(registry,snapshot,dict(path='cache/2024/8/16/1100.json.xz',sha256='a'*64))
    assert registry=={}


def test_player_alias_requires_continuity_and_corroboration_and_excludes_managers():
    import copy
    from experiments.data_ground_truth.bootstrap_aliases import corroborate
    def variant(code,first,last):
        return dict(code=code,first_name='A',second_name='B',position=2,observed_team_ids=[1],
                    distinct_snapshot_objects=3,first=dict(source_claimed_at=first),last=dict(source_claimed_at=last))
    entry=dict(season='2022-23',element=1,variants=[variant(20,'2022-08-01','2022-08-05'),variant(21,'2022-08-06','2023-05-20')])
    alias=corroborate(entry,21,['2022-09-01','2022-09-02'])
    assert alias['source_code']==20 and alias['canonical_code']==21 and not alias['eligible_predeadline']
    for key,value in [('position',5),('first_name','Different'),('distinct_snapshot_objects',1),('observed_team_ids',[2])]:
        bad=copy.deepcopy(entry);bad['variants'][0][key]=value
        with pytest.raises(ValueError):corroborate(bad,21,['2022-09-01','2022-09-02'])
    with pytest.raises(ValueError,match='appearance'):corroborate(entry,21,['2022-09-01'])
    with pytest.raises(ValueError,match='shared'):corroborate(entry,21,['2022-09-01','2022-09-02'],[20])
    bad=copy.deepcopy(entry);bad['variants'][0]['last']['source_claimed_at']='2022-08-07'
    with pytest.raises(ValueError,match='overlapping'):corroborate(bad,21,['2022-09-01','2022-09-02'])


def test_bootstrap_alias_is_scoped_preserves_source_and_does_not_admit_time():
    from experiments.data_ground_truth.bootstrap_state import apply_alias
    e=dict(id=1,code=20,element_type=2)
    alias=dict(canonical_code=21,scope='same_season_fpl_element_only',first_source_claimed_at='2022-08-01',last_source_claimed_at='2022-08-05')
    aliases={('2022-23',1,20):alias};candidate=dict(season='2022-23',source_claimed_at='2022-08-03')
    changed,applied=apply_alias(e,candidate,aliases)
    assert changed['code']==21 and applied and e['code']==20
    assert apply_alias(e,dict(candidate,season='2023-24'),aliases)==(e,False)
    with pytest.raises(ValueError,match='range'):apply_alias(e,dict(candidate,source_claimed_at='2022-08-08'),aliases)
    with pytest.raises(ValueError,match='entity'):apply_alias(dict(e,element_type=5),candidate,aliases)
    with pytest.raises(ValueError,match='integer'):apply_alias(dict(e,code=True),candidate,aliases)


def test_bootstrap_git_provenance_parses_offsets_and_requires_immutable_content():
    from experiments.data_ground_truth.bootstrap_time import parse_log,assess
    sha='a'*40;blob='b'*40;zero='0'*40;path='cache/2024/8/16/1238.json.xz'
    log=f'commit\t{sha}\t2024-08-16T13:38:36+01:00\t2024-08-16T12:38:36Z\n\n:000000 100644 {zero} {blob} A\t{path}\n'
    history=parse_log(log);row=assess(path,blob,history[path],'2024-08-16T17:30:00Z')
    assert row['commit_minus_claim_seconds']==36 and row['coherent_under_source_clock_assumption']
    assert row['author_committer_agree'] and row['available_at'] is None and not row['eligible_predeadline']
    changed=history[path]+[dict(history[path][0],status='M')]
    assert not assess(path,blob,changed,'2024-08-16T17:30:00Z')['coherent_under_source_clock_assumption']
    assert not assess(path,'c'*40,history[path],'2024-08-16T17:30:00Z')['coherent_under_source_clock_assumption']
    assert not assess(path,blob,history[path],'2024-08-16T12:38:20Z')['coherent_under_source_clock_assumption']
    with pytest.raises(ValueError,match='naive'):parse_log(log.replace('2024-08-16T12:38:36Z','2024-08-16T12:38:36'))
    with pytest.raises(ValueError,match='diff without'):parse_log(log.split('\n\n')[1])


def test_bootstrap_git_negative_clock_delay_never_becomes_coherent():
    from experiments.data_ground_truth.bootstrap_time import assess
    c=dict(new_blob='b'*40,status='A',commit='a'*40,committer_at='2024-08-16T12:37:00Z',author_at='2024-08-16T12:37:00Z')
    row=assess('cache/2024/8/16/1238.json.xz','b'*40,[c],'2024-08-16T17:30:00Z')
    assert row['commit_minus_claim_seconds']==-60 and not row['coherent_under_source_clock_assumption']


def test_publication_archive_filters_repository_and_reuses_verified_events(tmp_path, monkeypatch):
    import gzip
    from experiments.data_ground_truth import publication_archive as archive
    event=dict(id='event', type='PushEvent', repo=dict(id=archive.REPOSITORY_ID,name=archive.REPOSITORY),
               created_at='2024-08-17T06:15:00Z',public=True,payload=dict(head='a'*40,commits=[]))
    other=dict(event,repo=dict(id=999,name=archive.REPOSITORY))
    data=gzip.compress(('\n'.join(json.dumps(e) for e in [event,other])+'\n').encode())
    calls=[]
    def get(url, **kwargs):
        calls.append(url)
        return data, {'last-modified':'Sat, 17 Aug 2024 07:05:00 GMT'}
    monkeypatch.setattr(archive,'_get',get)
    record=archive.capture_hour(tmp_path,'2024-08-17-06')
    assert calls==['https://data.gharchive.org/2024-08-17-6.json.gz']
    assert record['scanned_events']==2 and len(record['events'])==1
    assert archive.capture_hour(tmp_path,'2024-08-17-06')==record and len(calls)==1
    assert len(list((tmp_path/'events').iterdir()))==1
    (tmp_path/'events'/record['events'][0]['source_event_sha256']).write_bytes(b'corrupt')
    with pytest.raises(ValueError,match='hash mismatch'):
        archive.capture_hour(tmp_path,'2024-08-17-06')


def test_publication_witness_requires_exact_public_commit_and_predeadline_time():
    from experiments.data_ground_truth.publication_archive import witness
    candidate=dict(season='2024-25',gw=1,path='cache/a',source_sha256='b'*64,commit='a'*40,
                   committer_at='2024-08-16T12:38:36Z',deadline='2024-08-16T17:30:00Z')
    event=dict(event_id='event',source_event_sha256='c'*64,head='a'*40,commit_shas=[],
               public=True,created_at='2024-08-16T12:38:38Z')
    hour=dict(hour='2024-08-16-12',compressed_sha256='d'*64,events=[event])
    assert witness(candidate,hour)['available_at']=='2024-08-16T12:38:38Z'
    for change in [dict(public=False),dict(public='true'),dict(head='e'*40),
                   dict(created_at=candidate['deadline']),dict(created_at='2024-08-16T12:38:35Z')]:
        row=witness(candidate,dict(hour,events=[dict(event,**change)]))
        assert row['available_at'] is None and not row['eligible_predeadline']
    assert witness(candidate,dict(hour,events=[]))['status']=='no_matching_public_push_in_requested_hour'
    assert witness(candidate,dict(hour,events=[dict(event,head='e'*40,commit_shas=['a'*40])]))['eligible_predeadline']


def test_publication_evidence_rejects_tampered_projection_and_wrong_repository():
    from experiments.data_ground_truth.publication_coverage import verify_event
    from experiments.data_ground_truth.publication_archive import REPOSITORY,REPOSITORY_ID
    event=dict(id='1',type='PushEvent',repo=dict(id=REPOSITORY_ID,name=REPOSITORY),
               created_at='2024-08-16T12:38:38Z',public=True,payload=dict(head='a'*40,commits=[]))
    data=json.dumps(event).encode()
    projection=dict(event_id='1',created_at=event['created_at'],public=True,head='a'*40,
                    commit_shas=[],source_event_sha256=raw.digest(data))
    verify_event(projection,data)
    with pytest.raises(ValueError,match='projection'):
        verify_event(dict(projection,created_at='2024-08-15T12:38:38Z'),data)
    with pytest.raises(ValueError,match='repository'):
        verify_event(projection,json.dumps(dict(event,repo=dict(id=0,name=REPOSITORY))).encode())
