from experiments.data_ground_truth.fixture_publication_alternatives import alternatives


def test_alternatives_exclude_future_original_wrong_season_and_stale_versions():
    c=dict(commit='original',deadline='2025-09-20T10:00:00Z',source_committer_at='2025-09-19T10:00:00Z')
    def row(revision,time,**changes):
        return dict(main_series=True,identity_verified=True,season='2025-26',revision=revision,committer_at=time,**changes)
    rows=[row('older','2025-09-10T10:00:00Z'),row('recent','2025-09-18T10:00:00Z'),
          row('original','2025-09-19T10:00:00Z'),row('future','2025-09-21T10:00:00Z'),row('stale','2025-09-01T10:00:00Z')]
    rows.extend([dict(rows[1],revision='derived',main_series=False),dict(rows[1],revision='unknown',identity_verified=False),dict(rows[1],revision='season',season='2026-27')])
    assert [r['revision'] for r in alternatives(c,rows)]==['recent','older']
    assert len(rows)==8


def test_alternative_age_boundary_is_explicit():
    c=dict(commit='original',deadline='2025-09-20T10:00:00Z',source_committer_at='2025-09-19T10:00:00Z')
    v=dict(main_series=True,identity_verified=True,season='2025-26',revision='boundary',committer_at='2025-09-06T10:00:00Z')
    assert alternatives(c,[v])==[v]
    assert alternatives(c,[dict(v,committer_at='2025-09-06T09:59:59Z')])==[]
