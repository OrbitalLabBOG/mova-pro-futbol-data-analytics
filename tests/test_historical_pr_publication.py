import json
from experiments.data_ground_truth.historical_pr_publication import project,witness


def event(**changes):
    pr=dict(merged=True,merged_at='2025-08-20T07:59:03Z',merge_commit_sha='a'*40,base=dict(repo=dict(id=24128688)))
    pr.update(changes)
    return dict(id='1',type='PullRequestEvent',public=True,repo=dict(id=24128688,name='vaastav/Fantasy-Premier-League'),
        created_at='2025-08-20T07:59:04Z',payload=dict(action='closed',pull_request=pr))


def test_only_public_completed_merges_are_projected():
    raw=event();assert project(json.dumps(raw).encode())['merge_commit_sha']=='a'*40
    assert project(json.dumps(event(merged=False)).encode()) is None
    assert project(json.dumps(event(base=dict(repo=dict(id=1)))).encode()) is None
    assert project(json.dumps(dict(raw,public=False)).encode()) is None
    raw['payload']['action']='opened'
    assert project(json.dumps(raw).encode()) is None


def test_public_merge_witness_uses_event_time_without_backdating():
    e=project(json.dumps(event()).encode());hour=dict(hour='2025-08-20-07',compressed_sha256='archive',events=[e])
    c=dict(season='2025-26',gw=2,deadline='2025-08-22T17:30:00Z',committer_at='2025-08-20T07:59:03Z',commit='a'*40,
        path='data/2025-26/fixtures.csv',source_sha256='raw',normalized_sha256='calendar')
    proof=witness(c,hour,None)
    assert proof['available_at']=='2025-08-20T07:59:04Z' and proof['proof_kind']=='exact_public_merge_commit'
    assert witness(dict(c,deadline='2025-08-20T07:59:04Z'),hour,None) is None
    assert witness(dict(c,committer_at='2025-08-20T07:59:04Z'),hour,None) is None
