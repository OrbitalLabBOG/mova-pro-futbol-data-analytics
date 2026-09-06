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
