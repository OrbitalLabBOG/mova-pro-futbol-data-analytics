import pytest
from experiments.data_ground_truth.calendar_evidence_index import combine


def inputs():
    target = dict(season='2026-27', gw=2, deadline='2026-08-28T17:30:00Z')
    shared = dict(target, available_at='2026-08-28T15:00:05Z')
    external = dict(shared, source_committer_at='2026-08-28T14:00:00Z',
                    proof={'eligible_predeadline': True}, normalized_sha256='external', object_root='external')
    own = dict(shared, observed_at='2026-08-28T15:00:00Z',
               evidence_origin='own_collector_ingestion_ledger', eligible_training=False,
               normalized_fixtures_sha256='own')
    return target, external, own


def test_overlapping_evidence_counts_deadline_once_preserves_both_origins():
    target, external, own = inputs()
    rows, report = combine([target], [external], [own])
    assert report['covered_deadlines'] == 1 and report['evidence_records'] == 2
    assert {r['source_clock_kind'] for r in rows} == {'git_committer_at', 'collection_started_at'}
    assert all(r['eligible_training'] is False for r in rows)
    assert report['missing'] == []
    for origin in ('external_publication', 'own_collector_ingestion_ledger'):
        assert report['source_clock_age'][origin]['within48h'] == 1


def test_deadline_exclusive_and_source_clock_order():
    target, external, own = inputs()
    for bad in [dict(own, available_at=target['deadline']),
                dict(own, observed_at='2026-08-28T16:00:00Z')]:
        with pytest.raises(ValueError, match='interval'):
            combine([target], [], [bad])


def test_duplicate_unknown_and_unproven_evidence_rejected():
    target, external, own = inputs()
    for targets, ext, internal in [([target, target], [], []),
        ([target], [external, external], []), ([target], [], [dict(own, gw=3)]),
        ([target], [dict(external, proof={'eligible_predeadline': False})], []),
        ([target], [], [dict(own, eligible_training=True)])]:
        with pytest.raises(ValueError):
            combine(targets, ext, internal)


def test_missing_targets_are_reported_without_inventing_evidence():
    target, _, own = inputs()
    missing = dict(target, gw=1, deadline='2026-08-21T17:30:00Z')
    _, report = combine([missing, target], [], [own])
    assert report['expected_deadlines'] == 2 and report['covered_deadlines'] == 1
    assert report['missing'] == [missing]
