"""Recount the frozen research labels independently of historical gate summaries."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import pandas as pd
from experiments.data_ground_truth.training_dataset import verify as verify_gt
from experiments.data_ground_truth.partial_label_package import verify as verify_partial

HERE = Path(__file__).parent

def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def validate(base: Path) -> dict:
    pointer = json.loads((HERE/'current-labels.json').read_text())
    package = base/'training-datasets'/pointer['dataset_id']
    manifest = verify_gt(package)
    if sha(package/'manifest.json') != pointer['manifest_sha256']:
        raise ValueError('official label pointer hash mismatch')
    partitions = []; splits = Counter()
    for entry in manifest['partitions']:
        path = package/entry['file']; frame = pd.read_csv(path, compression='gzip')
        required = ['season', 'element', 'fixture', 'minutes', 'total_points']
        if frame[required].isna().any().any():
            raise ValueError('missing label/key')
        if not frame.minutes.between(0, 90).all():
            raise ValueError('minutes outside 0..90')
        for col in ['element', 'fixture', 'minutes', 'total_points']:
            if frame[col].mod(1).ne(0).any():
                raise ValueError('noninteger label/key')
        partitions.append(dict(season=entry['season'], split=entry['split'],
            rows=len(frame), players=int(frame.element.nunique()), fixtures=int(frame.fixture.nunique()),
            zero_minute_rows=int(frame.minutes.eq(0).sum()), positive_minute_rows=int(frame.minutes.gt(0).sum()),
            duplicate_keys=int(frame.duplicated(['season','element','fixture']).sum()),
            file=entry['file'], bytes=path.stat().st_size, sha256=sha(path)))
        splits[entry['split']] += len(frame)
    rows = sum(p['rows'] for p in partitions)
    if rows != pointer['rows'] or manifest['manager_rows'] != pointer['manager_rows']:
        raise ValueError('official pointer counts mismatch')
    partial_pointer = json.loads((HERE/'current-partial-labels.json').read_text())
    partial = base/'partial-label-datasets'/partial_pointer['dataset_id']
    partial_manifest = verify_partial(partial)
    if sha(partial/'manifest.json') != partial_pointer['manifest_sha256']:
        raise ValueError('partial label pointer hash mismatch')
    return dict(schema='mova-data-gate-recount-v1', dataset_id=manifest['dataset_id'],
        manifest_sha256=pointer['manifest_sha256'], rows=rows, seasons=len(partitions),
        manager_rows=manifest['manager_rows'], splits=dict(splits), partitions=partitions,
        package_files=sum(1 for p in package.rglob('*') if p.is_file()),
        package_bytes=sum(p.stat().st_size for p in package.rglob('*') if p.is_file()),
        partial_dataset_id=partial_manifest['dataset_id'], partial_coverage=partial_manifest['coverage'],
        partial_package_files=sum(1 for p in partial.rglob('*') if p.is_file()),
        partial_package_bytes=sum(p.stat().st_size for p in partial.rglob('*') if p.is_file()),
        predeadline_replay_admitted=False, production_promoted=False)

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args=parser.parse_args()
    result=validate(args.base)
    args.out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k: result[k] for k in ('dataset_id','rows','seasons','manager_rows','splits','partial_coverage')}))
