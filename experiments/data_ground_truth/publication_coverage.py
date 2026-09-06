"""Verify archived event evidence and measure temporal coverage without admitting training."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import gzip
import io
import json
from pathlib import Path

from experiments.data_ground_truth.publication_archive import REPOSITORY, REPOSITORY_ID, aware, witness
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked


def verify_event(projected, raw):
    event = json.loads(raw)
    if event.get('type') != 'PushEvent' or event.get('repo', {}).get('name') != REPOSITORY or event['repo'].get('id') != REPOSITORY_ID:
        raise ValueError('event repository/type mismatch')
    payload = event['payload']
    expected = dict(event_id=event['id'], created_at=event['created_at'], public=event.get('public'),
        head=payload.get('head'), commit_shas=[c['sha'] for c in payload.get('commits', [])], source_event_sha256=digest(raw))
    if projected != expected:
        raise ValueError('event projection mismatch')


def build(archive_root: Path, provenance_root: Path, state_root: Path, out: Path):
    archive_bytes = (archive_root/'report.json').read_bytes()
    archive = json.loads(archive_bytes)
    provenance_bytes = checked(provenance_root/'report.json', archive['git_provenance_report_sha256'])
    provenance = json.loads(provenance_bytes)
    candidates = json.loads(checked(provenance_root/'candidates.json', provenance['artifacts']['candidates.json']))
    rows = json.loads(checked(archive_root/'witnesses.json', archive['witnesses_sha256']))
    expected_rows = []
    for c in candidates:
        hour = aware(c['committer_at']).strftime('%Y-%m-%d-%H')
        if hour not in archive['hour_report_sha256']:
            continue
        record = json.loads(checked(archive_root/'hours'/(hour+'.json'), archive['hour_report_sha256'][hour]))
        if record['hour'] != hour:
            raise ValueError('archive hour mismatch')
        for event in record['events']:
            verify_event(event, checked(archive_root/'events'/event['source_event_sha256'], event['source_event_sha256']))
        expected_rows.append(witness(c, record))
    if rows != expected_rows or len(rows) != archive['assessed_candidates']:
        raise ValueError('witness derivation mismatch')
    if sum(r['eligible_predeadline'] for r in rows) != archive['public_push_witnesses']:
        raise ValueError('witness count mismatch')
    indexed = {(r['season'], r['gw']): r for r in rows}
    if len(indexed) != len(rows):
        raise ValueError('duplicate deadline witness')
    state_bytes = (state_root/'report.json').read_bytes()
    state = json.loads(state_bytes)
    if state['source_manifest_sha256'] != provenance['source_manifest_sha256'] or state['candidates'] != len(candidates):
        raise ValueError('state provenance mismatch')
    seasons = {c['season']: dict(candidates=0, verified_deadlines=0, player_rows=0, verified_player_rows=0,
        manager_rows=0, verified_manager_rows=0) for c in candidates}
    for c in candidates:
        seasons[c['season']]['candidates'] += 1
    for r in rows:
        seasons[r['season']]['verified_deadlines'] += int(r['eligible_predeadline'])
    for kind in ('player', 'manager'):
        data = checked(state_root/(kind+'_states.csv.gz'), state['artifacts'][kind+'_states.csv.gz'])
        for row in csv.DictReader(io.StringIO(gzip.decompress(data).decode())):
            s = seasons[row['season']]
            s[kind+'_rows'] += 1
            proof = indexed.get((row['season'], int(row['gw'])))
            if proof:
                if row['source_sha256'] != proof['source_sha256'] or aware(row['deadline']) != aware(proof['deadline']):
                    raise ValueError('state/witness content or deadline mismatch')
                s['verified_'+kind+'_rows'] += int(proof['eligible_predeadline'])
    if sum(s['player_rows']+s['manager_rows'] for s in seasons.values()) != state['rows']:
        raise ValueError('state row count mismatch')
    result = dict(version='publication-coverage-v1', archive_report_sha256=digest(archive_bytes),
        state_report_sha256=digest(state_bytes), implementation_sha256=digest(Path(__file__).read_bytes()),
        seasons=seasons, statuses=dict(Counter(r['status'] for r in rows)),
        unavailable_hours=archive['expected_hours']-archive['acquired_hours'],
        availability_semantics='conservative_publication_upper_bound_from_exact_commit_public_PushEvent',
        training_admitted=False, state_package_changed=False, production_changed=False,
        limitations=['publication_does_not_prove_field_accuracy_or_selection_eligibility',
                     'five_full_candidate_seasons_do_not_cover_all_twelve_label_seasons',
                     'missing_event_does_not_prove_non_publication'])
    out.mkdir(parents=True, exist_ok=True)
    (out/'report.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ('archive-root', 'provenance-root', 'state-root', 'out'):
        ap.add_argument('--'+name, type=Path, required=True)
    args = ap.parse_args()
    print(json.dumps(build(args.archive_root, args.provenance_root, args.state_root, args.out), indent=2))


if __name__ == '__main__':
    main()
