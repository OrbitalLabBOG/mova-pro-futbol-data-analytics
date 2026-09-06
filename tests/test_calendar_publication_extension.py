import pytest

from experiments.data_ground_truth.calendar_publication_extension import capture, proof, scheduled_hour


def candidate():
    return dict(season='2025-26',gw=2,committer_at='2025-08-20T07:59:03Z',deadline='2025-08-20T10:00:00Z',
                commit='a'*40,path='data/2025-26/fixtures.csv',source_sha256='raw',normalized_sha256='calendar')


def test_hour_plan_respects_exclusive_deadline_and_skips_original_hours():
    c=candidate()
    assert scheduled_hour(c,2)=='2025-08-20-09'
    assert scheduled_hour(c,3) is None
    with pytest.raises(ValueError):scheduled_hour(c,1)


def test_merge_can_prove_calendar_without_push_and_never_at_deadline():
    c=candidate()
    event=dict(event_id='1',created_at='2025-08-20T09:00:01Z',merged_at='2025-08-20T09:00:00Z',
               merge_commit_sha='a'*40,source_event_sha256='event')
    hour=dict(hour='2025-08-20-09',compressed_sha256='archive',push_events=[],merge_events=[event])
    r=proof(c,hour,None)
    assert r['evidence_type']=='PullRequestEvent' and r['available_at']==event['created_at']
    assert proof(dict(c,deadline=event['created_at']),hour,None) is None


def test_offline_missing_hour_never_downloads(tmp_path,monkeypatch):
    monkeypatch.setattr('experiments.data_ground_truth.calendar_publication_extension._get',lambda *a,**k:pytest.fail('network'))
    with pytest.raises(OSError,match='offline'):capture(tmp_path,'2025-08-20-09',True)
