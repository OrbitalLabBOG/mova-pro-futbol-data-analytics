"""Load explicitly reviewed name claims; source evidence cannot force identities."""
from __future__ import annotations

import csv
from html.parser import HTMLParser
import io
import json
from pathlib import Path

from experiments.data_ground_truth.identity_2014 import name_tokens
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked


class PageText(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def validate_claim(claim, data, metadata):
    code = claim['official_player_code']
    if code not in metadata or name_tokens(metadata[code]['full_name']) != name_tokens(claim['FPL_name']):
        raise ValueError('reviewed claim does not match code-bound FPL name')
    if len(name_tokens(claim['variant'])) < 2:
        raise ValueError('reviewed variants require full names')
    if claim['kind'] == 'same_code_FPL_csv':
        rows = [r for r in csv.DictReader(io.StringIO(data.decode())) if r['code'] == code]
        if len(rows) != 1 or name_tokens(rows[0]['first_name']+' '+rows[0]['second_name']) != name_tokens(claim['variant']):
            raise ValueError('variant absent or ambiguous under source FPL code')
    elif claim['kind'] == 'reviewed_same_event_page':
        page = PageText(); page.feed(data.decode())
        text = ' '.join(' '.join(page.parts).split())
        if any(fragment not in text for fragment in claim['reviewed_fragments']):
            raise ValueError('reviewed event evidence absent')
    else:
        raise ValueError('unsupported name evidence kind')
    return dict(full_name=claim['variant'], evidence_kind=claim['kind'],
                source_sha256=claim['source_sha256'], source_url=claim['source_url'],
                bound_FPL_name=claim['FPL_name'], official_player_code=code)


def load(root, metadata):
    registry_path = Path(__file__).with_name('reviewed-name-claims.json')
    registry_bytes = registry_path.read_bytes(); registry = json.loads(registry_bytes)
    variants = {}; seen = set()
    for claim in registry['claims']:
        key = (claim['official_player_code'], claim['variant'])
        if key in seen:
            raise ValueError('duplicate reviewed claim')
        seen.add(key)
        data = checked(root/'objects'/claim['source_sha256'], claim['source_sha256'])
        variants.setdefault(key[0], []).append(validate_claim(claim, data, metadata))
    return variants, dict(registry_sha256=digest(registry_bytes),
                         validator_sha256=digest(Path(__file__).read_bytes()),
                         claims=len(seen), source_sha256=sorted({c['source_sha256'] for c in registry['claims']}))
