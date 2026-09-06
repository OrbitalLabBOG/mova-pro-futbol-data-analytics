"""Capture explicitly public historical FPL blobs, preserving unknown availability."""
from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from xml.etree import ElementTree as ET

from mova_fpl.data.sources import _get
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked

ACCOUNT = 'https://martinfplstats1337.blob.core.windows.net'
CONTAINERS = ('2020-fpl-data', '2021-fpl-data')


def listing(data: bytes, container: str) -> list[dict]:
    if container not in CONTAINERS:
        raise ValueError('unreviewed container')
    root = ET.fromstring(data)
    if root.tag != 'EnumerationResults' or root.findtext('NextMarker'):
        raise ValueError('incomplete or invalid listing')
    rows = []
    for blob in root.findall('./Blobs/Blob'):
        name = blob.findtext('Name')
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z_data.json', name or ''):
            raise ValueError('unexpected blob name')
        size = int(blob.findtext('./Properties/Content-Length'))
        md5 = blob.findtext('./Properties/Content-MD5')
        if not 0 < size <= 16*1024*1024 or len(base64.b64decode(md5, validate=True)) != 16:
            raise ValueError('invalid size or MD5')
        rows.append(dict(name=name, bytes=size, content_md5=md5,
                         listed_last_modified=blob.findtext('./Properties/Last-Modified'),
                         listed_etag=blob.findtext('./Properties/Etag')))
    if not rows or len({r['name'] for r in rows}) != len(rows):
        raise ValueError('empty or duplicate listing')
    return sorted(rows, key=lambda r:r['name'])


def validate(data: bytes, record: dict) -> dict:
    if len(data) != record['bytes'] or base64.b64encode(hashlib.md5(data).digest()).decode() != record['content_md5']:
        raise ValueError('blob differs from pinned listing')
    value = json.loads(data)
    if not isinstance(value, dict) or not all(isinstance(value.get(k), list) for k in ('events', 'elements', 'teams')):
        raise ValueError('not a bootstrap snapshot')
    events = value['events']
    if len(events) != 38 or {e['id'] for e in events} != set(range(1,39)):
        raise ValueError('invalid event universe')
    first = next(e['deadline_time'] for e in events if e['id'] == 1)
    year = datetime.fromisoformat(first.replace('Z', '+00:00')).year
    return dict(season=f'{year}-{str(year+1)[-2:]}', first_deadline=first,
                players=len(value['elements']), teams=len(value['teams']),
                declared_download_time=value.get('download_time'),
                current_events=[e['id'] for e in events if e.get('is_current')])


def capture(root: Path, container: str, item: dict, offline: bool) -> dict:
    if container not in CONTAINERS or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z_data.json', item.get('name', '')):
        raise ValueError('unreviewed blob URL')
    url = ACCOUNT+'/'+container+'/'+item['name']
    record_path = root/'records'/(digest(url.encode())+'.json')
    if record_path.exists():
        record = json.loads(record_path.read_text())
        if record['url'] != url or record['listing_item'] != item:
            raise ValueError('receipt mismatch')
        data = checked(root/'objects'/record['sha256'], record['sha256'])
        if validate(data, item) != record['content_summary']:
            raise ValueError('content summary mismatch')
        return record
    if offline:
        raise ValueError('missing offline blob')
    data, headers = _get(url, include_headers=True, timeout=60)
    summary = validate(data, item)
    sha = digest(data)
    obj = root/'objects'/sha
    obj.parent.mkdir(parents=True, exist_ok=True)
    if obj.exists():
        checked(obj, sha)
    else:
        temporary = obj.with_name(sha+'.'+digest(url.encode())+'.tmp')
        temporary.write_bytes(data); temporary.replace(obj)
    record = dict(url=url, container=container, listing_item=item, sha256=sha,
                  content_summary=summary, fetched_at=datetime.now(timezone.utc).isoformat(),
                  response_last_modified=headers.get('last-modified'), response_etag=headers.get('etag'),
                  available_at=None, eligible_predeadline=False, eligible_training=False)
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(json.dumps(record, indent=2)+'\n')
    return record


def build(root: Path, offline=False) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    records = []; listings = {}
    for container in CONTAINERS:
        path = root/(container+'-listing.xml')
        receipt = root/(container+'-listing-receipt.json')
        url = ACCOUNT+'/'+container+'?restype=container&comp=list&maxresults=5000'
        if path.exists():
            info = json.loads(receipt.read_text())
            if info['url'] != url: raise ValueError('listing URL mismatch')
            data = checked(path, info['sha256'])
        else:
            if offline: raise ValueError('missing listing')
            data = _get(url, timeout=60)
            listing(data, container)
            path.write_bytes(data)
            receipt.write_text(json.dumps(dict(url=url,sha256=digest(data),fetched_at=datetime.now(timezone.utc).isoformat()),indent=2)+'\n')
        items = listing(data, container)
        listings[container] = dict(sha256=digest(data), blobs=len(items), bytes=sum(x['bytes'] for x in items))
        with ThreadPoolExecutor(max_workers=4) as pool:
            records.extend(pool.map(lambda item:capture(root, container, item, offline), items))
        print(container, len(items), 'verified', flush=True)
    manifest = json.dumps(dict(records=records), indent=2, allow_nan=False)+'\n'
    (root/'manifest.json').write_text(manifest)
    seasons = {}
    for record in records:
        season = record['content_summary']['season']
        seasons[season] = seasons.get(season, 0)+1
    report = dict(version='azure-history-v1', listings=listings, snapshots=len(records), seasons=seasons,
                  manifest_sha256=digest(manifest.encode()), implementation_sha256=digest(Path(__file__).read_bytes()),
                  new_complete_label_seasons=0, training_admitted=False,
                  limitations=['bootstrap_states_not_player_fixture_labels','filenames_download_time_and_blob_metadata_not_publication_proof',
                               'listing_is_pinned_inventory_not_guaranteed_all_historical_captures'])
    (root/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True);p.add_argument('--offline',action='store_true')
    a=p.parse_args();print(json.dumps(build(a.root,a.offline),indent=2))
