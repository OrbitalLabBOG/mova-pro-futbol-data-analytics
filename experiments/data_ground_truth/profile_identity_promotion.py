"""Promote corroborated historical identities while preserving every observed label."""
from __future__ import annotations
import argparse
import csv
import gzip
import io
import json
from pathlib import Path
import shutil
import tempfile
from experiments.data_ground_truth import discovery_identity_enrichment as parent
from experiments.data_ground_truth import profile_sources
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked,verify

PARENT_ID='d4baf849fb4a051be103f8c469e61a4753edb0b4004f980a000fe5c86ef573db'

def derive(base,identities,evidence_sha,out):
    package=base/'training-datasets'/PARENT_ID;original=verify(package)
    manifest=json.loads(json.dumps(original));manifest.pop('dataset_id')
    entry=next(p for p in manifest['partitions'] if p['season']=='2014-15')
    reader=csv.DictReader(io.StringIO(gzip.decompress(checked(package/entry['file'],entry['sha256'])).decode()))
    fields=reader.fieldnames;rows=list(reader)
    updated,changes=parent.update_rows(rows,identities)
    stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=fields,lineterminator='\n');writer.writeheader();writer.writerows(updated)
    payload=gzip.compress(stream.getvalue().encode(),mtime=0)
    entry.update(sha256=digest(payload),official_identity_rows=sum(bool(r['official_player_code']) for r in updated),
                 season_scoped_identity_rows=sum(not r['official_player_code'] for r in updated))
    manifest.update(version='fpl-labels-v8',parent_dataset_id=PARENT_ID,
                    identity_extension=dict(evidence_sha256=evidence_sha,implementation_sha256=digest(Path(__file__).read_bytes()),
                                            players=len({r['element'] for r in changes}),rows=len(changes),
                                            method='same_season_observation_match_and_exact_full_name_profile',
                                            identity_only_not_future_features=True))
    manifest['dataset_id']=digest(json.dumps(manifest,sort_keys=True,separators=(',',':')).encode())
    out.mkdir(parents=True,exist_ok=True);target=out/manifest['dataset_id']
    if not target.exists():
        with tempfile.TemporaryDirectory(dir=out) as temporary:
            stage=Path(temporary)/'package';stage.mkdir()
            for group in ('partitions','quarantines','manager_partitions'):
                for p in original.get(group,[]):shutil.copyfile(package/p['file'],stage/p['file'])
            (stage/entry['file']).write_bytes(payload);(stage/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
            verify(stage);stage.rename(target)
    verify(target)
    for group in ('partitions','quarantines','manager_partitions'):
        for p in original.get(group,[]):
            if p['file']!=entry['file'] and (package/p['file']).read_bytes()!=(target/p['file']).read_bytes():raise ValueError('unrelated partition changed')
    return manifest,changes


def build(base,out,datasets):
    out.mkdir(parents=True,exist_ok=True)
    recorded=json.loads(Path(__file__).with_name('results-g98.json').read_text())
    expected=recorded['audit'];oldroot=base/'profile-audit-g98-v1'
    checked(oldroot/'report.json',recorded['report_sha256'])
    replay=profile_sources.build(base,out/'source_revalidated')
    # G99 pins G98's parent rather than following the mutable current pointer.
    for key,value in expected.items():
        if key!='implementation_sha256' and replay[key]!=value:raise ValueError('G98 evidence replay changed')
    for n,sha in expected['artifacts'].items():
        checked(oldroot/n,sha);checked(out/'source_revalidated'/n,sha)
    priorroot=base/'discovery-profile-extension-v2';prior=json.loads((priorroot/'report.json').read_text())
    if prior['dataset_id']!=PARENT_ID:raise ValueError('unexpected parent enrichment')
    priorbytes=checked(priorroot/'identities.json',prior['artifacts']['identities.json'])
    candidates=[r for r in json.loads(priorbytes) if r['status']!='corroborated_code_and_full_name']
    rawroot=base/'profile-source-g98';raw=checked(rawroot/'manifest.json',expected['manifest_sha256'])
    records=json.loads(raw)['records'];observed=[]
    for r in records:
        if r['path']!='data/players.1432930058.json':continue
        players=json.loads(checked(rawroot/'objects'/r['sha256'],r['sha256']))
        for key,p in players.items():
            if key!=str(p['id']):raise ValueError('source identity mismatch')
            observed.append(dict(code=p['code'],first_name=p['first_name'],second_name=p['second_name'],
                source_element=p['id'],source_sha256=r['sha256'],repository=r['repository'],revision=r['revision'],source_path=r['path']))
    identities=[parent.classify(dict(c,profile=c['source_profile']),observed) for c in candidates]
    if not identities or any(r['status']!='corroborated_code_and_full_name' for r in identities):raise ValueError('unresolved full-name witness')
    for r in identities:
        if any(w['source_element']!=r['player_id'] for w in r['exact_profile_witnesses']):raise ValueError('same-season ID disagreement')
    with (oldroot/'identity_candidates.csv').open() as stream:
        overlap={(int(r['element']),int(r['candidate_official_player_code'])) for r in csv.DictReader(stream)}
    if {(r['player_id'],r['source_code']) for r in identities}!=overlap:raise ValueError('observation and profile evidence differ')
    evidence=(json.dumps(identities,indent=2)+'\n').encode();(out/'identities.json').write_bytes(evidence)
    manifest,changes=derive(base,identities,digest(evidence),datasets)
    payload=(json.dumps(changes,indent=2)+'\n').encode();(out/'changes.json').write_bytes(payload)
    report=dict(version='profile-identity-promotion-v1',parent_dataset_id=PARENT_ID,
        source_audit_report_sha256=recorded['report_sha256'],prior_identity_evidence_sha256=digest(priorbytes),
        source_replay_implementation_sha256=replay['implementation_sha256'],implementation_sha256=digest(Path(__file__).read_bytes()),
        dataset_id=manifest['dataset_id'],manifest_sha256=digest((datasets/manifest['dataset_id']/'manifest.json').read_bytes()),
        dataset_rows=manifest['rows'],manager_rows=manifest['manager_rows'],enriched_players=len(identities),enriched_rows=len(changes),
        partition_2014=next(p for p in manifest['partitions'] if p['season']=='2014-15'),
        artifacts={'identities.json':digest(evidence),'changes.json':digest(payload)},
        all_non_identity_cells_preserved=True,unrelated_partitions_byte_identical=True,
        production_changed=False,model_training_run=False,predeadline_admission=False)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('base','out','datasets'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.base,a.out,a.datasets),indent=2))
