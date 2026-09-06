import subprocess
import pytest
from experiments.data_ground_truth.geek_publication import REPO,REPO_ID
from experiments.data_ground_truth.geek_publication_extension import git,proof


def test_git_ancestor_and_identical_blob_are_distinct_evidence(tmp_path):
    def command(*args):
        return subprocess.check_output(['git','-C',str(tmp_path),*args],stderr=subprocess.DEVNULL).decode().strip()
    command('init');command('config','user.name','Test');command('config','user.email','test@example.test')
    p=tmp_path/'app/js/data.json';p.parent.mkdir(parents=True);p.write_bytes(b'{"id":1}')
    command('add','.');command('commit','-m','source');source=command('rev-parse','HEAD')
    p.write_bytes(b'{"id":2}');command('commit','-am','later');head=command('rev-parse','HEAD')
    event=dict(type='PushEvent',public=True,repo=dict(id=REPO_ID,name=REPO),payload=dict(head=head))
    assert proof(tmp_path,source,b'{"id":1}',event)['evidence_kind']=='ancestor_public_push'
    command('checkout','--orphan','published');command('rm','-rf','.')
    p=tmp_path/'js/data.json';p.parent.mkdir(parents=True);p.write_bytes(b'{"id":1}')
    command('add','.');command('commit','-m','published bytes');event['payload']['head']=command('rev-parse','HEAD')
    result=proof(tmp_path,source,b'{"id":1}',event)
    assert result['evidence_kind']=='identical_blob_public_push' and result['published_path']=='js/data.json'
    with pytest.raises(ValueError,match='differs'):
        proof(tmp_path,source,b'{"id":99}',event)
