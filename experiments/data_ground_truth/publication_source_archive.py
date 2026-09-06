"""Retain exact previously hashed publication-source bytes; no new label inference."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from urllib.parse import urlparse
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked
from mova_fpl.data.sources import _get


def validate(record):
    url=urlparse(record['url'])
    if url.scheme!='https' or url.netloc!='data.gharchive.org' or url.query or url.fragment or not re.fullmatch(r'/\d{4}-\d{2}-\d{2}-\d{1,2}\.json\.gz',url.path):
        raise ValueError('unexpected publication source URL')
    if not re.fullmatch('[0-9a-f]{64}',record['compressed_sha256']) or type(record['compressed_bytes']) is not int or record['compressed_bytes']<=0:
        raise ValueError('invalid pinned publication object')


def build(reference, reference_sha, out):
    original=checked(reference,reference_sha);records=json.loads(original)
    for record in records:validate(record)
    if len({r['url'] for r in records})!=len(records):raise ValueError('duplicate publication URL')
    (out/'objects').mkdir(parents=True,exist_ok=True);(out/'records').mkdir(exist_ok=True)
    def capture(record):
        sha=record['compressed_sha256'];path=out/'objects'/sha;receipt=out/'records'/f'{sha}.json'
        if path.exists():data=checked(path,sha)
        else:
            data=_get(record['url'],timeout=120)
            if digest(data)!=sha:raise ValueError('publication source changed from observed hash')
        if len(data)!=record['compressed_bytes']:raise ValueError('publication source size differs')
        if not path.exists():
            temporary=path.with_suffix('.tmp');temporary.write_bytes(data);temporary.replace(path)
        if receipt.exists():
            result=json.loads(receipt.read_text())
            if (result['url']!=record['url'] or result['sha256']!=sha or result['bytes']!=len(data)
                    or result['reference_manifest_sha256']!=reference_sha):
                raise ValueError('cached publication receipt differs from reference')
            return result
        result=dict(url=record['url'],hour=record['hour'],sha256=sha,bytes=len(data),
            fetched_at=datetime.now(timezone.utc).isoformat(),reference_manifest_sha256=reference_sha,
            available_at=None,eligible_predeadline=False)
        receipt.write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(dict(captured_hour=record['hour'],bytes=len(data))),flush=True)
        return result
    with ThreadPoolExecutor(max_workers=3) as pool:acquired=list(pool.map(capture,records))
    report=dict(version='publication-source-archive-v1',records=acquired,errors=[],
        reference_manifest_sha256=reference_sha,implementation_sha256=digest(Path(__file__).read_bytes()),
        bytes=sum(r['bytes'] for r in acquired),new_FPL_labels=0,training_admitted=False,raw_redistribution_admitted=False)
    (out/'manifest.json').write_text(json.dumps(report,indent=2)+'\n');return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reference',type=Path,required=True);p.add_argument('--reference-sha',required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();r=build(a.reference,a.reference_sha,a.out);print(json.dumps(dict(records=len(r['records']),bytes=r['bytes'])))


if __name__=='__main__':main()
