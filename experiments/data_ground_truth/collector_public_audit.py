"""Audit collector public bytes and bind availability to completed ingestion ledger records."""
from __future__ import annotations
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
from experiments.data_ground_truth.additional_fixture_audit import read_fixture,signature
from experiments.data_ground_truth.bootstrap_state import integer,normalize
from experiments.data_ground_truth.bootstrap_time import aware
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked


def completion(record,runs):
    matching=[r for r in runs if r['artifact_path']==record['source_path'] and r['manifest_sha256']==record['source_manifest_sha256']]
    if len(matching)!=1:raise ValueError('ambiguous or missing ingestion binding')
    run=matching[0]
    if run['source_name']!='fpl_official' or run['payload_sha256']!=record['source_payload_sha256'] or run['status']!='completed' or run['finished_at'] is None:
        raise ValueError('incomplete or conflicting ingestion')
    finished=aware(run['finished_at'])
    if max(aware(run['started_at']),aware(record['observed_at']))>finished:raise ValueError('inconsistent ingestion clock')
    return dict(run_id=run['run_id'],available_at=finished.isoformat(),ingestion_started_at=run['started_at'])


def select(records,target):
    valid=[r for r in records if r['season']==target['season'] and aware(r['available_at'])<aware(target['deadline'])
           and r['deadlines'].get(str(target['gw']))==target['deadline']]
    return max(valid,key=lambda r:(aware(r['available_at']),r['source_manifest_sha256'])) if valid else None


def build(base,root,ledger_path,out):
    manifest_bytes=(root/'manifest.json').read_bytes();manifest=json.loads(manifest_bytes)
    ledger_bytes=ledger_path.read_bytes();ledger=json.loads(ledger_bytes)
    if ledger['transaction_read_only'] is not True:raise ValueError('readonly ledger export required')
    if manifest['account_payloads_exported'] is not False or set(manifest['exported_files'])!={'bootstrap-static.json','fixtures.json'}:
        raise ValueError('unexpected public export scope')
    ref_bytes=(base/'fixture-history-audit-v1/report.json').read_bytes();ref=json.loads(ref_bytes)
    versions=json.loads(checked(base/'fixture-history-audit-v1/versions.json',ref['artifacts']['versions.json']))
    final=max((v for v in versions if v['season']=='2026-27'),key=lambda v:aware(v['committer_at']))
    reference=json.loads(gzip.decompress(checked(base/'fixture-history-audit-v1/objects'/final['normalized_sha256'],final['normalized_sha256'])))
    expected=signature(reference)
    if expected is None:raise ValueError('invalid season fixture reference')
    sel_bytes=(base/'publication-selection-v1/report.json').read_bytes();sel=json.loads(sel_bytes)
    candidates=json.loads(checked(base/'publication-selection-v1/nominal_deadline_candidates.json',sel['artifacts']['nominal_deadline_candidates.json']))
    out.mkdir(parents=True,exist_ok=True);(out/'objects').mkdir(exist_ok=True)
    records=[];player_rows=0;manager_rows=0
    def save(rows):
        data=gzip.compress((json.dumps(rows,sort_keys=True,separators=(',',':'))+'\n').encode(),mtime=0);h=digest(data);(out/'objects'/h).write_bytes(data);return h
    for r in manifest['records']:
        original=json.loads(checked(root/'source-manifests'/r['source_manifest_sha256'],r['source_manifest_sha256']))
        if original['payload_sha256']!=r['source_payload_sha256'] or any(original[k]!=r[k] for k in ('source','season','method','observed_at')):
            raise ValueError('source manifest projection mismatch')
        if set(r['files'])!={'bootstrap-static.json','fixtures.json'} or any(original['files'][k]!=v for k,v in r['files'].items()):
            raise ValueError('public file projection mismatch')
        proof=completion(r,ledger['rows'])
        source={}
        for name,f in r['files'].items():
            data=checked(root/'objects'/f['sha256'],f['sha256'])
            if len(data)!=f['bytes']:raise ValueError('public source size mismatch')
            source[name]=data
        boot=json.loads(source['bootstrap-static.json']);fixtures=read_fixture(source['fixtures.json'],'fixtures.json')
        if signature(fixtures)!=expected:raise ValueError('fixture season identity mismatch')
        teams={integer(t['id'],'team'):integer(t['code'],'team code') for t in boot['teams']}
        if len(teams)!=20 or len(boot['teams'])!=20:raise ValueError('team population mismatch')
        deadlines={str(e['id']):aware(e['deadline_time']).isoformat().replace('+00:00','Z') for e in boot['events']}
        if len(deadlines)!=38 or len(boot['events'])!=38 or set(deadlines)!={str(i) for i in range(1,39)} or aware(deadlines['1']).year!=2026:raise ValueError('season calendar mismatch')
        states=[normalize(e,teams,None) for e in boot['elements']]
        if len({e['element'] for e in states})!=len(states) or len({e['official_player_code'] for e in states})!=len(states):raise ValueError('ambiguous player identity')
        players=sum(e['entity_type']=='player' for e in states);managers=len(states)-players
        player_rows+=players;manager_rows+=managers
        records.append(dict(season=r['season'],observed_at=r['observed_at'],source_manifest_sha256=r['source_manifest_sha256'],
                            source_files=r['files'],**proof,deadlines=deadlines,players=players,managers=managers,
                            normalized_fixtures_sha256=save(fixtures),normalized_states_sha256=save(states),
                            acquisition_duration_seconds=(aware(proof['available_at'])-aware(r['observed_at'])).total_seconds()))
    selected=[];missing=[]
    for c in candidates:
        if c['season']!='2026-27':continue
        r=select(records,c)
        if r is None:missing.append(c['gw']);continue
        selected.append(dict(season=c['season'],gw=c['gw'],deadline=c['deadline'],**{k:v for k,v in r.items() if k not in ('season','deadlines')},
                             age_from_collection_start_hours=(aware(c['deadline'])-aware(r['observed_at'])).total_seconds()/3600,
                             age_from_completed_ingestion_hours=(aware(c['deadline'])-aware(r['available_at'])).total_seconds()/3600,
                             evidence_origin='own_collector_ingestion_ledger',eligible_training=False))
    artifacts={}
    for name,data in [('captures.json',records),('selected_deadlines.json',selected)]:
        payload=(json.dumps(data,indent=2)+'\n').encode();(out/name).write_bytes(payload);artifacts[name]=digest(payload)
    report=dict(version='collector-public-audit-v1',source_manifest_sha256=digest(manifest_bytes),ledger_sha256=digest(ledger_bytes),
                reference_report_sha256=digest(ref_bytes),deadline_selection_report_sha256=digest(sel_bytes),implementation_sha256=digest(Path(__file__).read_bytes()),
                captures=len(records),player_snapshot_rows=player_rows,manager_snapshot_rows=manager_rows,fixture_snapshot_rows=380*len(records),
                completed_ledger_bindings=len(records),selected_deadlines=len(selected),missing_gws=missing,
                max_acquisition_duration_seconds=max(r['acquisition_duration_seconds'] for r in records),artifacts=artifacts,
                production_changed=False,training_admitted=False,limitations=['own_ledger_clock_not_external_publication_witness',
                   'exported_public_files_only_whole_bundle_payload_hash_not_recomputed','source_fields_preserved_without_model_admission'])
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('base-root','raw-root','ledger','out'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.base_root,a.raw_root,a.ledger,a.out),indent=2))


if __name__=='__main__':main()
