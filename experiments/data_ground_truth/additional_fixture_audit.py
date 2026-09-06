"""Classify additional fixture versions by complete FPL identity, keeping derived files separate."""
from __future__ import annotations
import argparse
import csv
import gzip
import io
import json
from pathlib import Path
from experiments.data_ground_truth.fixture_history_audit import parse
from experiments.data_ground_truth.bootstrap_time import aware
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked


def signature(rows):
    if len(rows)!=380 or any(not r.get('code') for r in rows):return None
    return tuple(sorted((r['id'],r['code'],r['team_h'],r['team_a']) for r in rows))


def read_fixture(data,path):
    if path.endswith('.json'):
        raw=json.loads(data)
        if not isinstance(raw,list) or not raw:raise ValueError('expected fixture array')
        buf=io.StringIO();writer=csv.DictWriter(buf,fieldnames=list(raw[0]));writer.writeheader();writer.writerows(raw);data=buf.getvalue().encode()
    return parse(data)


def build(root:Path,reference_root:Path,selection_root:Path,out:Path):
    raw=(root/'manifest.json').read_bytes();manifest=json.loads(raw)
    if manifest['errors'] or len(manifest['records'])!=manifest['expected_versions']:raise ValueError('incomplete acquisition')
    ref_bytes=(reference_root/'report.json').read_bytes();ref=json.loads(ref_bytes)
    versions=json.loads(checked(reference_root/'versions.json',ref['artifacts']['versions.json']))
    signatures={}
    for season in sorted({r['season'] for r in versions}):
        last=max((r for r in versions if r['season']==season),key=lambda r:r['committer_at'])
        rows=json.loads(gzip.decompress(checked(reference_root/'objects'/last['normalized_sha256'],last['normalized_sha256'])))
        key=signature(rows)
        if key is None or key in signatures:raise ValueError('ambiguous season reference')
        signatures[key]=season
    selection_bytes=(selection_root/'report.json').read_bytes();selection=json.loads(selection_bytes)
    candidates=json.loads(checked(selection_root/'nominal_deadline_candidates.json',selection['artifacts']['nominal_deadline_candidates.json']))
    out.mkdir(parents=True,exist_ok=True);(out/'objects').mkdir(exist_ok=True)
    records=[];errors=[]
    for r in manifest['records']:
        try:rows=read_fixture(checked(root/'objects'/r['sha256'],r['sha256']),r['path'])
        except (ValueError,KeyError,TypeError) as exc:
            errors.append(dict(path=r['path'],revision=r['revision'],error=str(exc)));continue
        season=signatures.get(signature(rows));payload=gzip.compress((json.dumps(rows,sort_keys=True,separators=(',',':'))+'\n').encode(),mtime=0)
        sha=digest(payload);(out/'objects'/sha).write_bytes(payload)
        records.append(dict(path=r['path'],revision=r['revision'],committer_at=r['committer_at'],source_sha256=r['sha256'],normalized_sha256=sha,
            fixtures=len(rows),season=season,main_series=r['path']=='data/fixtures.csv',identity_verified=season is not None,
            unknown_kickoffs=sum(x['kickoff_time'] is None for x in rows)))
    coverage=[]
    for c in candidates:
        if c['season']!='2025-26':continue
        prior=[r for r in records if r['main_series'] and r['season']==c['season'] and aware(r['committer_at'])<aware(c['deadline'])]
        item=dict(gw=c['gw'],deadline=c['deadline'],available_at=None,eligible_predeadline=False)
        if prior:
            r=max(prior,key=lambda r:(aware(r['committer_at']),r['revision']));rows=json.loads(gzip.decompress(checked(out/'objects'/r['normalized_sha256'],r['normalized_sha256'])))
            item.update(revision=r['revision'],source_committer_at=r['committer_at'],normalized_sha256=r['normalized_sha256'],
                nominal_age_hours=(aware(c['deadline'])-aware(r['committer_at'])).total_seconds()/3600,
                future_kickoffs=sum(x['kickoff_time'] is not None and aware(x['kickoff_time'])>aware(c['deadline']) for x in rows))
        else:item['status']='no_prior_verified_main_series'
        coverage.append(item)
    artifacts={}
    for name,value in [('versions.json',records),('errors.json',errors),('coverage.json',coverage)]:
        data=(json.dumps(value,indent=2)+'\n').encode();(out/name).write_bytes(data);artifacts[name]=digest(data)
    report=dict(version='additional-fixture-audit-v1',source_manifest_sha256=digest(raw),fixture_reference_report_sha256=digest(ref_bytes),
        selection_report_sha256=digest(selection_bytes),implementation_sha256=digest(Path(__file__).read_bytes()),parsed_versions=len(records),parse_errors=len(errors),
        identity_verified_versions=sum(r['identity_verified'] for r in records),main_series_versions=sum(r['main_series'] for r in records),
        main_series_seasons=sorted({r['season'] or 'unknown' for r in records if r['main_series']}),
        nominal_deadlines_with_prior_version=sum('revision' in r for r in coverage),within_48h=sum(r.get('nominal_age_hours',float('inf'))<=48 for r in coverage),
        future_kickoff_observations=sum(r.get('future_kickoffs',0) for r in coverage),artifacts=artifacts,
        production_changed=False,eligible_predeadline=False,limitations=['identity_match_does_not_prove_publication','derived_snapshots_excluded_from_deadline_selection','Git_commit_age_is_nominal_not_capture_age'])
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for arg in ('root','reference-root','selection-root','out'):ap.add_argument('--'+arg,type=Path,required=True)
    a=ap.parse_args();print(json.dumps(build(a.root,a.reference_root,a.selection_root,a.out),indent=2))


if __name__=='__main__':main()
