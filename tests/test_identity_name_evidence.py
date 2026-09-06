import pytest
from experiments.data_ground_truth.identity_name_evidence import validate_claim
from experiments.data_ground_truth.statsbomb_player_crosswalk import candidate_name_evidence


def claim(kind='same_code_FPL_csv'):
    return dict(official_player_code='168765', FPL_name='Joshua Onomah', variant='Josh Onomah',
                kind=kind, source_sha256='source-hash', source_url='https://example.org/evidence',
                reviewed_fragments=['Joshua Onomah started', 'Josh Onomah'])


def test_csv_name_is_bound_to_unique_official_code_not_element_id_or_similar_name():
    metadata={'168765':dict(full_name='Joshua Onomah')}
    csv=b'code,first_name,second_name\n168765,Josh,Onomah\n'
    assert validate_claim(claim(),csv,metadata)['full_name']=='Josh Onomah'
    for source in (csv.replace(b'168765',b'999'),csv+b'168765,Josh,Onomah\n'):
        with pytest.raises(ValueError):validate_claim(claim(),source,metadata)
    with pytest.raises(ValueError):validate_claim(claim(),csv,{'168765':dict(full_name='Someone Else')})


def test_reviewed_page_requires_registered_context_not_only_alias_occurrence():
    metadata={'168765':dict(full_name='Joshua Onomah')}
    assert validate_claim(claim('reviewed_same_event_page'),b'<p>Joshua Onomah started</p><a>Josh Onomah</a>',metadata)
    with pytest.raises(ValueError):
        validate_claim(claim('reviewed_same_event_page'),b'<p>Josh Onomah</p>',metadata)


def test_variant_cannot_cross_code_boundary_or_force_statsbomb_player_link():
    player=dict(player_name='Josh Onomah')
    candidate=dict(code='168765',name='Joshua Onomah')
    meta=dict(full_name='Joshua Onomah',verified_variants=[dict(full_name='Josh Onomah',source_sha256='evidence')])
    assert candidate_name_evidence(player,candidate,True,{'999':meta})[0] is None
    evidence,source=candidate_name_evidence(player,candidate,True,{'168765':meta})
    assert evidence=='fpl_metadata_variant_full_name' and source['source_sha256']=='evidence'
    assert candidate_name_evidence(dict(player_name='Other Onomah'),candidate,True,{'168765':meta})[0] is None


def pdf_claim(text):
    from experiments.data_ground_truth.raw import digest
    return dict(official_player_code='20480',FPL_name='Tim Krul',variant='Timothy Michael Krul',
                kind='reviewed_pdf_table',source_sha256='pdf-hash',source_url='https://example.org/roster.pdf',
                extracted_text_sha256=digest(text),page=2,reviewed_row='23 Tim KRUL KRUL Timothy Michael KRUL')


def test_pdf_claim_requires_the_reviewed_row_on_the_registered_page():
    text=b'cover\n\f\n23 Tim KRUL KRUL Timothy Michael KRUL'
    metadata={'20480':dict(full_name='Tim Krul')}
    result=validate_claim(pdf_claim(text),b'%PDF-fixture',metadata,text)
    assert result['page']==2 and result['full_name']=='Timothy Michael Krul'
    wrong=b'23 Tim KRUL KRUL Timothy Michael KRUL\n\f\nother page'
    with pytest.raises(ValueError):validate_claim(pdf_claim(wrong),b'%PDF-fixture',metadata,wrong)


def test_pdf_evidence_rejects_changed_extraction_missing_pdf_or_ambiguous_row():
    text=b'cover\n\f\n23 Tim KRUL KRUL Timothy Michael KRUL'
    metadata={'20480':dict(full_name='Tim Krul')}
    with pytest.raises(ValueError):validate_claim(pdf_claim(text),b'%PDF-fixture',metadata,text+b'changed')
    with pytest.raises(ValueError):validate_claim(pdf_claim(text),b'HTML instead of PDF',metadata,text)
    with pytest.raises(ValueError):validate_claim(pdf_claim(text),b'%PDF-fixture',metadata)
    duplicate=text+b' 23 Tim KRUL KRUL Timothy Michael KRUL'
    with pytest.raises(ValueError):validate_claim(pdf_claim(duplicate),b'%PDF-fixture',metadata,duplicate)
