"""Cross-check snapshot bytes and claimed clocks against pinned Git history."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from experiments.data_ground_truth.bootstrap_archive import claimed_time
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked


def aware(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('naive Git or deadline timestamp')
    return result.astimezone(timezone.utc)


def parse_log(data: str):
    history, current = defaultdict(list), None
    for line in data.splitlines():
        if not line:
            continue
        if line.startswith('commit\t'):
            _, sha, committer, author = line.split('\t')
            if not re.fullmatch('[0-9a-f]{40}', sha):
                raise ValueError('invalid commit hash')
            current = dict(commit=sha, committer_at=aware(committer).isoformat(), author_at=aware(author).isoformat())
        elif line.startswith(':'):
            if current is None:
                raise ValueError('diff without commit')
            fields, path = line.split('\t', 1)
            old_mode, new_mode, old_blob, new_blob, status = fields[1:].split()
            if not re.fullmatch('[0-9a-f]{40}', old_blob) or not re.fullmatch('[0-9a-f]{40}', new_blob):
                raise ValueError('abbreviated or invalid blob')
            if status not in ('A', 'M', 'D', 'T'):
                raise ValueError('unsupported history change')
            history[path].append(dict(**current, old_blob=old_blob, new_blob=new_blob, status=status))
        else:
            raise ValueError('unexpected Git export line')
    return dict(history)


def assess(path, blob, changes, deadline=None):
    source_time = datetime.fromisoformat(claimed_time(path)).replace(tzinfo=timezone.utc)
    matching = [r for r in changes if r['new_blob'] == blob]
    immutable = len(changes) == 1 and len(matching) == 1 and matching[0]['status'] == 'A'
    row = dict(path=path, git_blob=blob, history_changes=len(changes),
        matching_content_changes=len(matching), single_addition=immutable,
        source_claimed_at=claimed_time(path), source_clock_assumption='UTC',
        available_at=None, eligible_predeadline=False)
    if immutable:
        change = matching[0]
        commit_time = aware(change['committer_at'])
        lag = (commit_time-source_time).total_seconds()
        row.update(commit=change['commit'], committer_at=change['committer_at'], author_at=change['author_at'],
                   commit_minus_claim_seconds=lag, author_committer_agree=change['author_at']==change['committer_at'])
        # File clock precision is one minute; report delay without tuning a threshold to results.
        row['nonnegative_commit_delay'] = lag >= 0
        if deadline is not None:
            row['deadline'] = deadline
            row['commit_before_deadline'] = commit_time < aware(deadline)
            row['coherent_under_source_clock_assumption'] = lag >= 0 and source_time < aware(deadline) and row['commit_before_deadline'] and row['author_committer_agree']
    elif deadline is not None:
        row.update(deadline=deadline, coherent_under_source_clock_assumption=False)
    return row


def build(root: Path, log: Path, audit_root: Path, out: Path):
    raw = (root/'manifest.json').read_bytes()
    manifest = json.loads(raw)
    if manifest['errors'] or len(manifest['records']) != manifest['expected_files']:
        raise ValueError('incomplete acquisition')
    inventory = json.loads(checked(root/'inventory.json', manifest['inventory_sha256']))
    if inventory['sha'] != manifest['revision'] or inventory['truncated']:
        raise ValueError('invalid pinned inventory')
    blobs = {e['path']: e['sha'] for e in inventory['tree'] if e['type']=='blob'}
    log_bytes = log.read_bytes()
    history = parse_log(log_bytes.decode())
    audit = json.loads((audit_root/'report.json').read_text())
    if audit['manifest_sha256'] != digest(raw) or audit['errors']:
        raise ValueError('candidate source mismatch')
    candidates = json.loads(checked(audit_root/'nominal_deadline_candidates.json', audit['artifacts']['nominal_deadline_candidates.json']))
    records = {r['path']: r for r in manifest['records'] if r['path'].startswith('cache/')}
    rows = []
    for path, record in sorted(records.items()):
        data = checked(root/'objects'/record['sha256'], record['sha256'])
        blob = hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        if blob != blobs[path]:
            raise ValueError('source bytes differ from pinned Git blob')
        rows.append(dict(source_sha256=record['sha256'], **assess(path, blob, history.get(path, []))))
    selected = []
    for c in candidates:
        if records[c['path']]['sha256'] != c['sha256']:
            raise ValueError('candidate content mismatch')
        selected.append(dict(season=c['season'], gw=c['gw'], source_sha256=c['sha256'],
            **assess(c['path'], blobs[c['path']], history.get(c['path'], []), c['deadline'])))
    out.mkdir(parents=True, exist_ok=True)
    artifacts = {}
    for name, content in [('snapshots.json', rows), ('candidates.json', selected)]:
        payload = (json.dumps(content, indent=2)+'\n').encode()
        (out/name).write_bytes(payload)
        artifacts[name] = digest(payload)
    delays = [r['commit_minus_claim_seconds'] for r in rows if 'commit_minus_claim_seconds' in r]
    report = dict(version='bootstrap-time-v1', revision=manifest['revision'], source_manifest_sha256=digest(raw),
        git_log_sha256=digest(log_bytes), implementation_sha256=digest(Path(__file__).read_bytes()),
        snapshots=len(rows), single_addition_snapshots=sum(r['single_addition'] for r in rows),
        negative_commit_delays=sum(d<0 for d in delays), min_commit_delay_seconds=min(delays) if delays else None,
        max_commit_delay_seconds=max(delays) if delays else None,
        author_committer_disagreements=sum(r.get('author_committer_agree') is False for r in rows),
        unknown_author_committer_comparisons=sum('author_committer_agree' not in r for r in rows),
        candidates=len(selected), coherent_candidates=sum(r['coherent_under_source_clock_assumption'] for r in selected),
        artifacts=artifacts, verified_publication_times=0, eligible_predeadline=False,
        limitation='Git_dates_are_source_claims_not_independent_proof_of_historical_publication')
    (out/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for arg in ('root', 'log', 'audit-root', 'out'):
        ap.add_argument('--'+arg, type=Path, required=True)
    args = ap.parse_args()
    print(json.dumps(build(args.root, args.log, args.audit_root, args.out), indent=2))


if __name__ == '__main__':
    main()
