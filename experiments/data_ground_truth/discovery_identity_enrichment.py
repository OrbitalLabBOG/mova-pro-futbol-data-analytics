"""Corroborate declared historical codes with full profiles and derive immutable GT identities."""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
import csv
import gzip
import io
import json
from pathlib import Path
import shutil
import tempfile
import unicodedata

from experiments.data_ground_truth import discovery_2014 as parent
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked,verify


def name(value):
    return ' '.join(unicodedata.normalize('NFKC',value).casefold().split())


def classify(candidate,profiles):
    full=name(candidate['profile']['first_name']+' '+candidate['profile']['second_name'])
    evidence=[r for r in profiles if r['code']==candidate['source_code']]
    exact=[r for r in evidence if full and name(r['first_name']+' '+r['second_name'])==full]
    status='corroborated_code_and_full_name' if exact else ('name_variant_requires_review' if evidence else 'no_later_profile')
    return dict(player_id=candidate['player_id'],source_code=candidate['source_code'],status=status,
                reference_rows=candidate['reference_rows'],source_profile=candidate['profile'],
                exact_profile_witnesses=exact,other_same_code_profiles=[r for r in evidence if r not in exact])


def update_rows(rows,identities):
    accepted={r['player_id']:r for r in identities if r['status']=='corroborated_code_and_full_name'}
    if len({r['source_code'] for r in accepted.values()})!=len(accepted):raise ValueError('duplicate accepted code')
    occupied={int(r['official_player_code']):int(r['element']) for r in rows if r['official_player_code']}
    for pid,r in accepted.items():
        if r['source_code'] in occupied and occupied[r['source_code']]!=pid:raise ValueError('code already assigned')
    changed=[];output=[];seen=Counter()
    for original in rows:
        row=dict(original);pid=int(row['element']);candidate=accepted.get(pid)
        if candidate:
            if row['official_player_code'] or row['source_official_player_code'] or row['identity_key']!=f'fpl:2014-15:{pid}':
                raise ValueError('only unresolved identity may be enriched')
            if row['season']!='2014-15' or row['entity_type']!='player':raise ValueError('unexpected enrichment scope')
            code=candidate['source_code'];row.update(official_player_code=str(code),source_official_player_code=str(code),identity_key=f'opta:{code}')
            changed.append(dict(element=pid,fixture=int(row['fixture']),source_code=code));seen[pid]+=1
        if any(row[k]!=original[k] for k in row if k not in ('official_player_code','source_official_player_code','identity_key')):
            raise ValueError('non-identity value changed')
        output.append(row)
    if dict(seen)!={pid:r['reference_rows'] for pid,r in accepted.items()}:raise ValueError('candidate row population mismatch')
    return output,changed


def derive(base,identities,evidence_sha,output):
    package=base/'training-datasets'/parent.GT_ID;original=verify(package)
    manifest=json.loads(json.dumps(original));manifest.pop('dataset_id')
    entry=next(p for p in manifest['partitions'] if p['season']=='2014-15')
    raw=gzip.decompress(checked(package/entry['file'],entry['sha256']))
    reader=csv.DictReader(io.StringIO(raw.decode()));fields=reader.fieldnames;rows=list(reader)
    enriched,changed=update_rows(rows,identities)
    stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=fields,lineterminator='\n');writer.writeheader();writer.writerows(enriched)
    data=gzip.compress(stream.getvalue().encode(),mtime=0)
    entry.update(sha256=digest(data),official_identity_rows=sum(bool(r['official_player_code']) for r in enriched),
                 season_scoped_identity_rows=sum(not r['official_player_code'] for r in enriched))
    manifest.update(version='fpl-labels-v6',parent_dataset_id=parent.GT_ID,
                    identity_enrichment=dict(evidence_sha256=evidence_sha,implementation_sha256=digest(Path(__file__).read_bytes()),
                                             players=len({r['element'] for r in changed}),rows=len(changed),
                                             method='declared_2014_code_and_later_exact_full_name_profile',
                                             future_profiles_used_for_stable_identity_only=True))
    manifest['dataset_id']=digest(json.dumps(manifest,sort_keys=True,separators=(',',':')).encode())
    target=output/manifest['dataset_id'];output.mkdir(parents=True,exist_ok=True)
    if not target.exists():
        with tempfile.TemporaryDirectory(dir=output) as temporary:
            staging=Path(temporary)/'package';staging.mkdir()
            for group in ('partitions','quarantines','manager_partitions'):
                for p in original.get(group,[]):
                    shutil.copyfile(package/p['file'],staging/p['file'])
            (staging/entry['file']).write_bytes(data);(staging/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
            verify(staging);staging.rename(target)
    verify(target)
    for group in ('partitions','quarantines','manager_partitions'):
        for p in original.get(group,[]):
            if p['file']!=entry['file'] and (package/p['file']).read_bytes()!=(target/p['file']).read_bytes():
                raise ValueError('unrelated partition changed')
    return manifest,changed


def build(base,out,datasets):
    out.mkdir(parents=True,exist_ok=True)
    parent_root=base/'discovery-2014-audit-v4';parent.build(base,out/'parent_revalidated')
    for file in ('report.json','identity-candidates.json','cell-disagreements.json','gt-cell-disagreements.json'):
        if (parent_root/file).read_bytes()!=(out/'parent_revalidated'/file).read_bytes():raise ValueError('parent reproduction mismatch')
    report_bytes=(parent_root/'report.json').read_bytes();report=json.loads(report_bytes)
    candidates=json.loads(checked(parent_root/'identity-candidates.json',report['artifacts']['identity-candidates.json']))
    candidates=[r for r in candidates if r['gt_v5_status']=='new_source_code_candidate']
    rawroot=base/'raw-history-v2';manifest_bytes=(rawroot/'manifest.json').read_bytes();rawmanifest=json.loads(manifest_bytes)
    profiles=[];inputs=[]
    for record in rawmanifest['records']:
        if record['repository']!='vaastav/Fantasy-Premier-League' or not record['path'].endswith('/players_raw.csv'):continue
        season=record['path'].split('/')[1]
        data=checked(rawroot/'objects'/record['sha256'],record['sha256']);seen=set()
        for r in csv.DictReader(io.StringIO(data.decode('utf-8-sig'))):
            if r.get('element_type')=='5':continue
            code=parent.integer(r['code'])
            if code in seen:raise ValueError('duplicate profile code in season')
            seen.add(code)
            profiles.append(dict(season=season,code=code,first_name=r['first_name'],second_name=r['second_name'],
                                 source_sha256=record['sha256'],source_path=record['path'],repository=record['repository'],revision=record['revision']))
        inputs.append(dict(path=record['path'],sha256=record['sha256']))
    identities=[classify(c,profiles) for c in candidates]
    payload=(json.dumps(identities,indent=2)+'\n').encode();(out/'identities.json').write_bytes(payload)
    package,changes=derive(base,identities,digest(payload),datasets)
    changes_bytes=(json.dumps(changes,indent=2)+'\n').encode();(out/'changes.json').write_bytes(changes_bytes)
    result=dict(version='discovery-identity-enrichment-v1',parent_report_sha256=digest(report_bytes),raw_manifest_sha256=digest(manifest_bytes),
                implementation_sha256=digest(Path(__file__).read_bytes()),profile_inputs=inputs,profile_rows=len(profiles),candidates=len(candidates),
                statuses=dict(Counter(r['status'] for r in identities)),enriched_rows=len(changes),
                dataset_id=package['dataset_id'],dataset_rows=package['rows'],manager_rows=package['manager_rows'],
                partition_2014=next(p for p in package['partitions'] if p['season']=='2014-15'),
                artifacts={'identities.json':digest(payload),'changes.json':digest(changes_bytes)},production_changed=False,
                model_training_run=False,predeadline_admission=False,
                limitations=['future_metadata_used_only_for_stable_identity_not_features','name_variants_without_exact_witness_remain_unresolved'])
    (out/'report.json').write_text(json.dumps(result,indent=2)+'\n');return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('base-root','out','datasets-root'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.base_root,a.out,a.datasets_root),indent=2))


if __name__=='__main__':main()
