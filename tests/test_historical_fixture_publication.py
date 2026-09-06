import gzip
import json
import pytest
from experiments.data_ground_truth.historical_fixture_publication import extract,validate_event_projection,witness,REPOSITORY,REPOSITORY_ID


def test_historical_source_scope_and_raw_event_binding(tmp_path):
    base=dict(id='1',type='PushEvent',repo=dict(name=REPOSITORY,id=REPOSITORY_ID),public=True,
        created_at='2025-08-01T08:50:00Z',payload=dict(head='a'*40,commits=[]))
    unrelated=dict(base,repo=dict(name='Schwetche/fpl_project',id=1042951725))
    rows,scanned=extract(gzip.compress((json.dumps(unrelated)+'\n'+json.dumps(base)+'\n').encode()),tmp_path)
    assert scanned==2 and len(rows)==1
    h=dict(hour='2025-08-01-08',compressed_sha256='hash',events=rows)
    validate_event_projection(tmp_path,h)
    c=dict(season='2025-26',gw=1,path='data/2025-26/fixtures.csv',source_sha256='raw',commit='a'*40,
        committer_at='2025-08-01T08:49:42Z',deadline='2025-08-15T17:30:00Z')
    assert witness(c,h)['eligible_predeadline']
    rows[0]['head']='b'*40
    with pytest.raises(ValueError,match='altered'):validate_event_projection(tmp_path,h)


def test_historical_witness_does_not_backdate_later_push():
    c=dict(season='2025-26',gw=1,path='data/2025-26/fixtures.csv',source_sha256='raw',commit='a',
        committer_at='2025-08-01T08:49:42Z',deadline='2025-08-15T17:30:00Z')
    h=dict(hour='2025-08-15-18',compressed_sha256='hash',events=[dict(event_id='1',public=True,head='a',commit_shas=[],created_at='2025-08-15T18:00:00Z',source_event_sha256='event')])
    p=witness(c,h)
    assert not p['eligible_predeadline'] and p['available_at'] is None


def test_extended_window_is_bounded_by_deadline_and_72_hours():
    from experiments.data_ground_truth.historical_fixture_publication import candidate_hours
    c=dict(season='2025-26',gw=2,committer_at='2025-08-20T07:59:03Z',deadline='2025-08-22T17:30:00Z')
    assert candidate_hours(c,[])==['2025-08-20-07','2025-08-20-08']
    hours=candidate_hours(c,['2025-26:2'])
    assert len(hours)==59 and hours[-1]=='2025-08-22-17'
    assert len(candidate_hours(dict(c,deadline='2025-09-22T17:30:00Z'),['2025-26:2']))==73


def test_offline_missing_hour_never_downloads(tmp_path,monkeypatch):
    import experiments.data_ground_truth.historical_fixture_publication as module
    def forbidden(*args):raise AssertionError('offline must not download')
    monkeypatch.setattr(module,'capture_hour',forbidden)
    folder=tmp_path/'failures';folder.mkdir();(folder/'2021-10-25-09.json').write_text(json.dumps({'reason':'HTTP 404'}))
    with pytest.raises(OSError,match='HTTP 404'):module.get_hour(tmp_path,'2021-10-25-09',True)
