import gzip
import json
import pytest
from experiments.data_ground_truth.fixture_publication import extract, validate_event_projection, witness, REPOSITORY, REPOSITORY_ID


def test_publication_requires_exact_repo_commit_and_deadline(tmp_path):
    raw=dict(id='1',type='PushEvent',repo=dict(name=REPOSITORY,id=REPOSITORY_ID),public=True,
        created_at='2025-09-01T10:05:00Z',payload=dict(head='a'*40,commits=[]))
    foreign=dict(raw,repo=dict(name=REPOSITORY,id=999))
    data=gzip.compress((json.dumps(foreign)+'\n'+json.dumps(raw)+'\n').encode())
    events,count=extract(data,tmp_path)
    assert count==2 and len(events)==1
    hour=dict(events=events,hour='2025-09-01-10',compressed_sha256='archive-hash')
    validate_event_projection(tmp_path,hour)
    candidate=dict(season='2025-26',gw=4,path='data/fixtures.csv',source_sha256='raw-hash',
        commit='a'*40,committer_at='2025-09-01T10:00:00Z',deadline='2025-09-01T11:00:00Z')
    assert witness(candidate,hour)['eligible_predeadline'] is True
    assert witness(dict(candidate,commit='b'*40),hour)['eligible_predeadline'] is False
    assert witness(dict(candidate,deadline='2025-09-01T10:05:00Z'),hour)['eligible_predeadline'] is False
    events[0]['created_at']='2025-09-01T09:00:00Z'
    with pytest.raises(ValueError,match='altered'):validate_event_projection(tmp_path,hour)


def test_private_push_is_not_publication_evidence():
    candidate=dict(season='2025-26',gw=4,path='data/fixtures.csv',source_sha256='raw',commit='a',
        committer_at='2025-09-01T10:00:00Z',deadline='2025-09-01T11:00:00Z')
    hour=dict(hour='2025-09-01-10',compressed_sha256='hash',events=[dict(public=False,head='a',commit_shas=[])])
    assert witness(candidate,hour)['eligible_predeadline'] is False


def test_ancestry_proof_uses_git_graph_and_rejects_reverse_direction(tmp_path):
    import subprocess
    repo=tmp_path/'repo';repo.mkdir()
    def git(*args):
        return subprocess.check_output(['git','-C',str(repo),*args],text=True,stderr=subprocess.DEVNULL).strip()
    git('init')
    (repo/'fixtures.csv').write_text('first')
    git('add','fixtures.csv')
    git('-c','user.name=Test','-c','user.email=test@example.com','commit','-m','first')
    first=git('rev-parse','HEAD')
    (repo/'fixtures.csv').write_text('second')
    git('add','fixtures.csv')
    git('-c','user.name=Test','-c','user.email=test@example.com','commit','-m','second')
    second=git('rev-parse','HEAD')
    candidate=dict(season='2025-26',gw=4,path='data/fixtures.csv',source_sha256='raw',commit=first,
        committer_at='2025-09-01T10:00:00Z',deadline='2025-09-01T11:00:00Z')
    event=dict(public=True,head=second,commit_shas=[],created_at='2025-09-01T10:05:00Z',event_id='1',source_event_sha256='event')
    hour=dict(hour='2025-09-01-10',compressed_sha256='hash',events=[event])
    proof=witness(candidate,hour,repo)
    assert proof['eligible_predeadline'] and proof['proof_kind']=='ancestor_of_public_head'
    reverse=dict(hour,events=[dict(event,head=first)])
    assert witness(dict(candidate,commit=second),reverse,repo)['eligible_predeadline'] is False
