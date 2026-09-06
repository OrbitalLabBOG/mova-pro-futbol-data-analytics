from experiments.data_ground_truth.calendar_staleness_audit import previous,horizon_changes


def row(**overrides):
    r=dict(season='2021-22',gw=30,repository='source',source_committer_at='2022-03-18T18:17:20Z',
           available_at='2022-03-18T18:17:35Z',deadline='2022-03-18T18:30:00Z',proof={'eligible_predeadline':True})
    return dict(r,**overrides)


def test_old_publication_is_observable_but_foreign_future_or_unproven_sources_are_not():
    target=dict(season='2021-22',gw=32,deadline='2022-04-08T17:30:00Z')
    source=row()
    assert previous([source],target)==source
    assert previous([row(season='2020-21'),row(gw=32),row(proof={'eligible_predeadline':False}),
                     row(available_at=target['deadline']),row(available_at='2022-03-18T18:17:00Z')],target) is None


def test_horizon_counts_keep_unassigned_fixtures_separate_and_stop_at_season_end():
    old=[dict(id=1,team_h=1,team_a=2,event=37),dict(id=2,team_h=1,team_a=3,event=None)]
    later=[dict(id=1,team_h=1,team_a=2,event=38),dict(id=2,team_h=1,team_a=3,event=39)]
    changes=horizon_changes(old,later,37)
    assert len(changes)==4
    assert {x['gw'] for x in changes}=={37,38}
    assert not any(x['club']==3 for x in changes)
    assert changes[0]==dict(club=1,gw=37,observed_older_count=1,later_unproven_count=0)
