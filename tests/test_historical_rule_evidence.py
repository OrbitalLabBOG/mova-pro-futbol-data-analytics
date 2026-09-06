import json
import pytest
from experiments.data_ground_truth.historical_rule_evidence import annotate,capture,visible
from experiments.data_ground_truth.raw import digest


def article():
    return dict(article_id='123',title='Official rule',displayed_date_text='01 Jan 2020',
                assertions=[dict(dimension='chip_inventory',anchor='additional chip',statement={'count':1})])


def test_visible_evidence_excludes_script_and_normalizes_entities():
    data=b'<h1>Official rule</h1><script>additional chip</script><style>hidden</style><p>01 Jan 2020 &amp; additional <b>chip</b></p>'
    text=visible(data)
    rows=annotate(article(),text)
    assert 'hidden' not in text and '&' in text
    row=rows[0]
    assert text[row['anchor_start']:row['anchor_end']]=='additional chip'
    assert row['available_at'] is None and not row['eligible_replay'] and not row['eligible_training']


def test_missing_date_or_ambiguous_anchor_cannot_accredit_statement():
    for text in ('Official rule additional chip',
                 'Official rule 01 Jan 2020 additional chip additional chip',
                 'Official rule 01 Jan 2020 unrelated'):
        with pytest.raises(ValueError):annotate(article(),text)


def test_offline_requires_archived_source_and_verifies_bytes(tmp_path):
    with pytest.raises(OSError,match='missing offline'):capture(tmp_path,article(),True)
    data=b'<h1>Official rule</h1>';sha=digest(data)
    (tmp_path/'objects').mkdir();(tmp_path/'objects'/sha).write_bytes(data)
    (tmp_path/'records').mkdir()
    record=dict(url='https://www.premierleague.com/en/news/123',sha256=sha,bytes=len(data))
    path=tmp_path/'records/123.json';path.write_text(json.dumps(record))
    assert capture(tmp_path,article(),True)==record
    (tmp_path/'objects'/sha).write_bytes(b'corrupt')
    with pytest.raises(ValueError):capture(tmp_path,article(),True)


def test_article_id_cannot_escape_allowlisted_source(tmp_path):
    with pytest.raises(ValueError,match='numeric'):
        capture(tmp_path,dict(article(),article_id='../other'),True)
