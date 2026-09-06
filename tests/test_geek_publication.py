from experiments.data_ground_truth.geek_publication import REPO,REPO_ID,witness


def event():
    return dict(type='PushEvent',public=True,repo=dict(id=REPO_ID,name=REPO),id='event',
        created_at='2015-08-15T16:17:57Z',payload=dict(head='sha',commits=[]),_source_sha256='hash')


def test_exact_public_push_uses_event_time_and_does_not_admit_deadline():
    result=witness('sha','2015-08-15T16:14:22Z',[event()])
    assert result['available_at']=='2015-08-15T16:17:57Z' and not result['eligible_predeadline']
    assert witness('other','2015-08-15T16:14:22Z',[event()])['available_at'] is None


def test_private_wrong_repository_and_time_conflicts_fail_closed():
    e=event()
    for bad in [dict(e,public=False),dict(e,repo=dict(id=999,name=REPO))]:
        assert witness('sha','2015-08-15T16:14:22Z',[bad])['available_at'] is None
    assert witness('sha','2015-08-15T17:00:00Z',[e])['status']=='push_precedes_committer_time'
