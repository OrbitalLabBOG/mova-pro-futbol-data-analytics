"""Acquire pinned bootstrap snapshots with source-claimed, untrusted timestamps."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import json
from pathlib import Path
import re

from experiments.data_ground_truth.raw import capture, digest

REPOSITORY = 'Randdalf/fplcache'
PROVENANCE = {'README.md', 'LICENSE', 'cache.py', '.github/workflows/cache.yml'}


def claimed_time(path: str) -> str:
    match = re.fullmatch(r'cache/(\d{4})/(\d{1,2})/(\d{1,2})/(\d{2})(\d{2})\.json\.xz', path)
    if not match:
        raise ValueError('invalid snapshot path')
    # The source uses datetime.today(), without a timezone. Do not invent UTC.
    return datetime(*map(int, match.groups())).isoformat()


def acquire(root: Path, inventory: Path, revision: str) -> dict:
    raw = inventory.read_bytes()
    tree = json.loads(raw)
    if tree.get('sha') != revision or tree.get('truncated', True):
        raise ValueError('invalid pinned snapshot inventory')
    entries = [r for r in tree['tree'] if r.get('type') == 'blob' and
               (r['path'].startswith('cache/') or r['path'] in PROVENANCE)]
    paths = [r['path'] for r in entries]
    if len(paths) != len(set(paths)) or not PROVENANCE.issubset(paths):
        raise ValueError('incomplete or duplicate snapshot inventory')
    times = {p: claimed_time(p) for p in paths if p not in PROVENANCE}
    if not times:
        raise ValueError('no snapshots')
    root.mkdir(parents=True, exist_ok=True)
    (root / 'inventory.json').write_bytes(raw)
    records, errors = [], []
    sizes = {r['path']: r['size'] for r in entries}
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = {pool.submit(capture, root, REPOSITORY, revision, p): p for p in paths}
        for i, job in enumerate(as_completed(jobs), 1):
            path = jobs[job]
            try:
                record = dict(job.result())
                if record['bytes'] != sizes[path]:
                    raise ValueError('inventory byte count mismatch')
                if path in times:
                    record.update(source_claimed_at=times[path], source_timezone=None,
                                  timestamp_evidence='path_and_naive_source_clock_not_verified_publication')
                records.append(record)
            except Exception as exc:
                errors.append(dict(path=path, error=type(exc).__name__))
            if i % 250 == 0:
                print(json.dumps(dict(completed=i, total=len(paths), errors=len(errors))), flush=True)
    report = dict(version='bootstrap-acquisition-v1', repository=REPOSITORY, revision=revision,
                  inventory_sha256=digest(raw), expected_files=len(paths), expected_snapshots=len(times),
                  records=sorted(records, key=lambda r: r['path']), errors=sorted(errors, key=lambda r: r['path']))
    (root / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, required=True)
    ap.add_argument('--inventory', type=Path, required=True)
    ap.add_argument('--revision', required=True)
    args = ap.parse_args()
    result = acquire(args.root, args.inventory, args.revision)
    print(json.dumps(dict(files=len(result['records']), errors=result['errors'])), flush=True)
    if result['errors']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
