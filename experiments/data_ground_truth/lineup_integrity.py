"""Contrast archived confirmed lineups with retrospective FPL starter sets."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import gzip
import io
import json
from pathlib import Path

from experiments.data_ground_truth.preseason_supplemental import code_key
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked


def starter_difference(provider, reference):
    return dict(extra=sorted(provider-reference), missing=sorted(reference-provider),
                status='equal' if provider == reference else 'different')


def historical_starters(rows, players, reference):
    starters = set(); unknown = 0
    for row in rows:
        if row['is_starting'] != 'True': continue
        player = row.get('player_id')
        code = players.get(code_key(player)) if player else None
        if code is None: unknown += 1
        else: starters.add(code)
    difference = starter_difference(starters, reference)
    if unknown: difference['status'] = 'unknown'
    return dict(unknown_players=unknown, comparison=difference,
                recovery_candidate=not unknown and difference['status']=='equal')


def build(details_root, supplemental_root, raw_root, history_root, out):
    details_bytes = (details_root/'report.json').read_bytes(); details = json.loads(details_bytes)
    supp_bytes = (supplemental_root/'report.json').read_bytes(); supp = json.loads(supp_bytes)
    if details['dataset_id'] != supp['dataset_id']:
        raise ValueError('different GT versions')
    raw_bytes = (raw_root/'manifest.json').read_bytes(); raw = json.loads(raw_bytes)
    players = {}; metadata_sources = []
    for r in raw['records']:
        if r['repository'] != 'olbauday/FPL-Core-Insights' or not r['path'].startswith('data/2025-2026/By Gameweek/') or not r['path'].endswith('/players.csv'):
            continue
        body = checked(raw_root/'objects'/r['sha256'], r['sha256'])
        metadata_sources.append(dict(path=r['path'],sha256=r['sha256']))
        for row in csv.DictReader(io.StringIO(body.decode())):
            player = code_key(row['player_id']); code = code_key(row['player_code'])
            if player in players and players[player] != code:
                raise ValueError('ambiguous player code')
            players[player] = code
    if len(metadata_sources) != 38:
        raise ValueError('incomplete player metadata')
    observations = [json.loads(line) for line in gzip.decompress(checked(details_root/'observations.jsonl.gz', details['artifacts']['observations.jsonl.gz'])).splitlines()]
    lineups = [r for r in observations if r['table'] == 'lineups']
    fixtures = {r['raw']['match_id']: r['fixture'] for r in lineups}
    fpl = {}; expected = defaultdict(set); unknown_reference = Counter()
    payload = checked(supplemental_root/'components.jsonl.gz', supp['artifacts']['components.jsonl.gz'])
    for line in gzip.decompress(payload).splitlines():
        row = json.loads(line)
        if row['season'] != '2025-26': continue
        key = (row['fixture'], code_key(row['official_player_code']))
        if key in fpl: raise ValueError('duplicate FPL appearance')
        fpl[key] = row['cells']['starts']
        value = fpl[key]
        if value['status'] != 'valid': unknown_reference[key[0]] += 1
        elif value['value'] == 1: expected[key[0]].add(key[1])
        elif value['value'] != 0: raise ValueError('non-binary FPL starts')
    actual = defaultdict(set); unknown_provider = Counter(); comparisons = []; counts = Counter()
    for entry in lineups:
        row = entry['raw']; fixture = entry['fixture']; player = code_key(row['player_id'])
        code = players.get(player)
        if row['is_starting'] not in ('True','False'): raise ValueError('non-boolean starter flag')
        is_starting = row['is_starting'] == 'True'
        if is_starting:
            if code is None: unknown_provider[fixture] += 1
            else: actual[fixture].add(code)
        reference = fpl.get((fixture, code))
        if code is None: status = 'no_player_mapping'
        elif reference is None: status = 'no_FPL_reference'
        elif reference['status'] != 'valid': status = 'unknown_FPL_starts'
        else: status = 'equal' if int(is_starting) == reference['value'] else 'different'
        counts[status] += 1
        comparisons.append(dict(fixture=fixture, player_id=player, player_code=code,
            provider_starts=is_starting, FPL_starts=reference, status=status,
            source_sha256=entry['source_sha256'], path=entry['path'], csv_row=entry['csv_row']))
    matches = []
    for match, fixture in sorted(fixtures.items()):
        difference = starter_difference(actual[fixture], expected[fixture])
        status = difference['status']
        if unknown_provider[fixture] or unknown_reference[fixture] or fixture not in expected:
            status = 'unknown'
        matches.append(dict(match_id=match,fixture=fixture,provider_starters=len(actual[fixture]),
            FPL_starters=len(expected[fixture]),status=status,extra=difference['extra'],missing=difference['missing'],
            unknown_provider_starters=unknown_provider[fixture],unknown_reference_starts=unknown_reference[fixture],
            retrospective_starter_set_consistent=status=='equal',eligible_predeadline=False,training_admitted=False))
    history_bytes = (history_root/'manifest.json').read_bytes(); history = json.loads(history_bytes)
    revisions = ('4f12bc1069f59137fcb03e34ab8bcf60502f1b22','b18f816fbaa21db5b55f9c4af117da4d0f8f11c1')
    scope = {(rev,f'data/2025-2026/By Tournament/Premier League/GW{gw}/lineups.csv') for rev in revisions for gw in (32,33)}
    if history['errors'] or len(history['records']) != len(scope) or {(r['revision'],r['path']) for r in history['records']} != scope:
        raise ValueError('incomplete history scope')
    target = {m['match_id'] for m in matches if m['status'] != 'equal'}; historical = []
    for r in history['records']:
        if r['repository'] != 'olbauday/FPL-Core-Insights': raise ValueError('unexpected history repository')
        body = checked(history_root/'objects'/r['sha256'],r['sha256'])
        groups = defaultdict(list)
        for row in csv.DictReader(io.StringIO(body.decode())): groups[row['match_id']].append(row)
        for match in sorted(target & set(groups)):
            assessment = historical_starters(groups[match], players, expected[fixtures[match]])
            historical.append(dict(match_id=match,revision=r['revision'],source_sha256=r['sha256'], **assessment))
    out.mkdir(parents=True,exist_ok=True)
    for name, rows in [('match-quality.json', matches),('row-comparisons.json',comparisons),('historical-comparisons.json',historical)]:
        (out/name).write_text(json.dumps(rows,indent=2)+'\n')
    report = dict(version='lineup-integrity-v1',dataset_id=details['dataset_id'],
        details_report_sha256=digest(details_bytes),supplemental_report_sha256=digest(supp_bytes),
        raw_manifest_sha256=digest(raw_bytes),history_manifest_sha256=digest(history_bytes),
        implementation_sha256=digest(Path(__file__).read_bytes()),metadata_sources=metadata_sources,
        player_identities=len(players),row_comparisons=dict(counts),
        match_status=dict(Counter(m['status'] for m in matches)),
        historical_comparisons=len(historical),historical_recovery_candidates=sum(r['recovery_candidate'] for r in historical),
        new_FPL_labels=0,production_changed=False,training_admitted=False,
        limitations=['retrospective_FPL_starts_not_independent_match_video_validation',
            'starter_set_agreement_not_complete_bench_or_substitution_validation',
            'current_metadata_not_proof_of_historical_identity_publication',
            'confirmed_label_not_proof_of_predeadline_availability',
            'sampled_history_not_exhaustive_no_raw_repair'],
        artifacts={n:digest((out/n).read_bytes()) for n in ('match-quality.json','row-comparisons.json','historical-comparisons.json')})
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('details-root','supplemental-root','raw-root','history-root','out'): p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args(); print(json.dumps(build(a.details_root,a.supplemental_root,a.raw_root,a.history_root,a.out),indent=2))


if __name__=='__main__': main()
