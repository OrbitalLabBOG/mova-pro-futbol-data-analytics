from experiments.data_ground_truth.season_identity_signatures import signature_candidates, supporting_name


def test_signature_requires_full_fixture_club_equality_and_two_distinct_matches():
    signature={(100,4),(101,4)}
    rows,_=signature_candidates({1:signature},{'10':signature},{'10':{100,101}})
    assert rows[0]['status']=='unique_signature'
    assert signature_candidates({1:{(100,4)}},{'10':{(100,4)}},{'10':{100}})[0]==[]
    assert signature_candidates({1:signature},{'10':{(100,4),(101,8)}},{'10':{100,101}})[0]==[]
    assert signature_candidates({1:signature|{(102,4)}},{'10':signature},{'10':{100,101}})[0]==[]


def test_shared_profile_cannot_be_disambiguated_by_filtering_already_known_players():
    signature={(100,4),(101,4)}
    rows,_=signature_candidates({1:signature,2:signature},{'10':signature},{'10':{100,101}})
    assert rows[0]['status']=='ambiguous_signature'
    rows,_=signature_candidates({1:signature},{'10':signature,'20':signature},{'10':{100,101},'20':{100,101}})
    assert rows[0]['status']=='ambiguous_signature'


def test_incomplete_and_uncoded_archive_profiles_still_block_false_uniqueness():
    signature={(100,4),(101,4)}
    for competitor in ('20','missing_code:99'):
        rows,_=signature_candidates({1:signature},{'10':signature,competitor:signature},{'10':{100,101},competitor:{100,101,102}})
        assert rows[0]['status']=='ambiguous_signature'
    rows,_=signature_candidates({1:signature},{'10':signature},{'10':{100,101,102}})
    assert rows[0]['status']=='incomplete_FPL_signature'


def test_name_guard_is_additional_evidence_not_unrestricted_fuzzy_matching():
    assert supporting_name('Rob Elliot','Robert Elliot')
    assert supporting_name('Samuel Mark Byram','Sam Byram')
    assert not supporting_name('Rob Elliott','Robert Elliot')
    assert not supporting_name('David Elliot','Robert Elliot')
    assert not supporting_name('Elliot','Robert Elliot')
