from experiments.data_ground_truth.statsbomb_player_crosswalk import resolve, compatible_names, archive_code


def witness(player,code,fixture):return dict(statsbomb_player_id=player,official_player_code=code,fixture=fixture)


def test_duplicate_row_not_second_fixture_witness():
    w=witness(1,'10',100)
    assert resolve([w,w])=={}
    assert resolve([w,witness(1,'10',101)])=={1:'10'}


def test_second_candidate_or_shared_official_code_prevents_acceptance():
    base=[witness(1,'10',100),witness(1,'10',101)]
    assert resolve(base+[witness(1,'11',102)])=={}
    assert resolve(base+[witness(2,'10',100),witness(2,'10',101)])=={}


def test_name_normalization_requires_two_tokens():
    assert compatible_names('Mesut Özil','Mesut Ozil')
    assert not compatible_names('Silva','David Silva')
    assert not compatible_names('David Silva','Bernardo Silva')
    assert archive_code('15073.0')=='15073'
    assert archive_code('') is None


def test_even_single_witness_competitor_blocks_reciprocal_uniqueness():
    rows=[witness(1,'10',100),witness(1,'10',101),witness(2,'10',102)]
    assert resolve(rows)=={}


def test_single_token_requires_explicit_alias_and_enabled_mode():
    from experiments.data_ground_truth.statsbomb_player_crosswalk import name_evidence
    player={'player_name':'Willian Borges da Silva','player_nickname':'Willian'}
    assert name_evidence(player,'Willian') is None
    assert name_evidence(player,'Willian',True)=='declared_alias'
    assert name_evidence({'player_name':'Willian Borges da Silva'},'Willian',True) is None
    assert name_evidence(player,'William',True) is None


def test_alias_must_match_whole_normalized_name_not_subset():
    from experiments.data_ground_truth.statsbomb_player_crosswalk import name_evidence
    player={'player_name':'Francesc Fabregas i Soler','player_nickname':'Cesc Fàbregas'}
    assert name_evidence(player,'Cesc Fabregas',True)=='declared_alias'
    assert name_evidence(player,'Cesc',True) is None


def test_FPL_full_name_must_be_bound_to_the_same_official_code():
    from experiments.data_ground_truth.statsbomb_player_crosswalk import candidate_name_evidence
    player={'player_name':'Fernando Francisco Reges','player_nickname':None}
    candidate={'code':'52538','name':'Fernando'}
    metadata={'full_name':'Fernando Francisco Reges','source_sha256':'evidence'}
    assert candidate_name_evidence(player,candidate,True,{'999':metadata})[0] is None
    kind,source=candidate_name_evidence(player,candidate,True,{'52538':metadata})
    assert kind=='fpl_metadata_full_name'
    assert source==metadata


def test_missing_code_requires_unique_full_name_and_same_fixture_played_label():
    from experiments.data_ground_truth.statsbomb_player_crosswalk import recover_archive_codes
    observation=dict(playerName='Rahman Baba', official_player_code='', team_id='8', matchId_events='100', minutesPlayed='90')
    metadata={'118335':dict(full_name='Abdul Rahman Baba',source_sha256='raw-fpl-hash')}
    label=dict(fixture='100',official_player_code='118335',minutes='90')
    recovered,audit=recover_archive_codes([observation],metadata,[label])
    assert recovered[2]['official_player_code']=='118335'
    assert audit[0]['fpl_name_source']['source_sha256']=='raw-fpl-hash'
    assert recover_archive_codes([observation],metadata,[label|{'fixture':'101'}])[0]=={}
    assert recover_archive_codes([observation],metadata,[label|{'minutes':'0'}])[0]=={}
    assert recover_archive_codes([observation],metadata|{'99':metadata['118335']},[label])[0]=={}
    assert recover_archive_codes([observation|{'playerName':'Baba'}],metadata,[label])[0]=={}


def test_recovery_never_overwrites_existing_code_or_assigns_two_rows_to_one_player():
    from experiments.data_ground_truth.statsbomb_player_crosswalk import recover_archive_codes
    observation=dict(playerName='Yann Kermorgant',official_player_code='',team_id='91',matchId_events='100',minutesPlayed='37')
    metadata={'44558':dict(full_name='Yann Kermorgant')}
    labels=[dict(fixture='100',official_player_code='44558',minutes='37')]
    assert recover_archive_codes([observation,observation],metadata,labels)[0]=={}
    assert recover_archive_codes([observation,observation|{'official_player_code':'44558'}],metadata,labels)[0]=={}
    assert recover_archive_codes([observation|{'official_player_code':'999'}],metadata,labels)==({},[])


def test_recovered_proposal_still_needs_two_distinct_matches_for_identity():
    from experiments.data_ground_truth.statsbomb_player_crosswalk import recover_archive_codes
    observation=dict(playerName='Victor Ibarbo',official_player_code='',team_id='57',matchId_events='100',minutesPlayed='8')
    recovered,_=recover_archive_codes([observation],{'59380':dict(full_name='Víctor Ibarbo')},
        [dict(fixture='100',official_player_code='59380',minutes='8')])
    assert recovered
    assert resolve([witness(1,recovered[2]['official_player_code'],100)])=={}
