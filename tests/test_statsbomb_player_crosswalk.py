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
