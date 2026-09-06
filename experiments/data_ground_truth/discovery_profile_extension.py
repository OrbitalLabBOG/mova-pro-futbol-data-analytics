"""Extend GT v6 identities using a pinned historical FPL profile dump."""
from __future__ import annotations
import argparse
from collections import Counter
import csv
import gzip
import io
import json
from pathlib import Path
import shutil
import tempfile

from experiments.data_ground_truth import discovery_identity_enrichment as parent
from experiments.data_ground_truth.discovery_2014 import integer
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked,verify

PARENT_ID='58e2e08833a157601e3e6bf75ea71adcd84211bf96a2139e9490b8936aa9e7cb'


def profiles(dump,source):
    result=[];ids=set();codes=set()
    for key,r in dump.items():
        code=integer(r['code']);pid=integer(r['id'])
        if code in codes or pid in ids:raise ValueError('duplicate dump identity')
        if key!=r['web_name']:raise ValueError('dump name key mismatch')
        if not r['first_name'].strip() or not r['second_name'].strip():raise ValueError('incomplete profile name')
        codes.add(code);ids.add(pid)
        result.append(dict(code=code,source_element=pid,first_name=r['first_name'],second_name=r['second_name'],
                           source_sha256=source['sha256'],repository=source['repository'],revision=source['revision'],source_path=source['path']))
    return result


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
    manifest.update(version='fpl-labels-v7',parent_dataset_id=PARENT_ID,
                    identity_extension=dict(evidence_sha256=evidence_sha,implementation_sha256=digest(Path(__file__).read_bytes()),
                                            players=len({r['element'] for r in changes}),rows=len(changes),
                                            method='declared_code_and_exact_full_name_in_historical_FPL_dump',
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
    original_root=base/'discovery-identity-enrichment-v2'
    parent.build(base,out/'parent_revalidated',base/'training-datasets')
    for file in ('report.json','identities.json','changes.json'):
        if (original_root/file).read_bytes()!=(out/'parent_revalidated'/file).read_bytes():raise ValueError('parent reproduction mismatch')
    report_bytes=(original_root/'report.json').read_bytes();report=json.loads(report_bytes)
    if report['dataset_id']!=PARENT_ID:raise ValueError('parent dataset mismatch')
    candidates=json.loads(checked(original_root/'identities.json',report['artifacts']['identities.json']))
    candidates=[r for r in candidates if r['status']!='corroborated_code_and_full_name']
    raw=base/'raw-history-snapshots';manifest_bytes=(raw/'manifest.json').read_bytes();manifest=json.loads(manifest_bytes)
    sources=[r for r in manifest['records'] if r['repository']=='clwatkins/fantasy_premier_league' and r['path']=='Data/FPL_API_Dump.json']
    if len(sources)!=1:raise ValueError('ambiguous profile dump')
    source=sources[0];data=checked(raw/'objects'/source['sha256'],source['sha256'])
    if len(data)!=source['bytes']:raise ValueError('source size mismatch')
    observed=profiles(json.loads(data),source)
    # The source record carries capture uncertainty; no nominal season clock becomes availability.
    identities=[parent.classify(dict(c,profile=c['source_profile']),observed) for c in candidates]
    evidence_bytes=(json.dumps(identities,indent=2)+'\n').encode();(out/'identities.json').write_bytes(evidence_bytes)
    package,changes=derive(base,identities,digest(evidence_bytes),datasets)
    changes_bytes=(json.dumps(changes,indent=2)+'\n').encode();(out/'changes.json').write_bytes(changes_bytes)
    result=dict(version='discovery-profile-extension-v1',parent_report_sha256=digest(report_bytes),raw_manifest_sha256=digest(manifest_bytes),
                source=source,implementation_sha256=digest(Path(__file__).read_bytes()),profile_rows=len(observed),candidates=len(candidates),
                statuses=dict(Counter(r['status'] for r in identities)),enriched_rows=len(changes),dataset_id=package['dataset_id'],
                dataset_rows=package['rows'],manager_rows=package['manager_rows'],
                partition_2014=next(p for p in package['partitions'] if p['season']=='2014-15'),
                artifacts={'identities.json':digest(evidence_bytes),'changes.json':digest(changes_bytes)},
                production_changed=False,model_training_run=False,predeadline_admission=False,
                limitations=['name_keyed_dump_may_omit_players_with_colliding_display_names','future_metadata_for_stable_identity_only'])
    (out/'report.json').write_text(json.dumps(result,indent=2)+'\n');return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('base-root','out','datasets-root'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.base_root,a.out,a.datasets_root),indent=2))


if __name__=='__main__':main()
