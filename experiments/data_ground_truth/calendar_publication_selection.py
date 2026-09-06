"""Combine fully revalidated calendar witnesses without splicing calendar rows or hiding age."""
from __future__ import annotations
import argparse
import gzip
import json
from pathlib import Path
from experiments.data_ground_truth import historical_fixture_publication as historical
from experiments.data_ground_truth import historical_pr_publication as merged
from experiments.data_ground_truth import fixture_publication as additional
from experiments.data_ground_truth.fixture_publication_alternatives import verify_candidate
from experiments.data_ground_truth.bootstrap_time import aware
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked


def choose(rows):
    selected={}
    for r in rows:
        if not r['proof']['eligible_predeadline'] or not aware(r['source_committer_at'])<=aware(r['available_at'])<aware(r['deadline']):raise ValueError('unproven or future calendar')
        key=(r['season'],r['gw']);previous=selected.get(key)
        if previous and aware(previous['deadline'])!=aware(r['deadline']):raise ValueError('deadline disagreement')
        if previous is None or (aware(r['source_committer_at']),r['repository'])>(aware(previous['source_committer_at']),previous['repository']):selected[key]=r
    return [selected[k] for k in sorted(selected)]


def build(base:Path,out:Path):
    inputs={}
    def report(name):
        data=(base/name/'report.json').read_bytes();inputs[name]=digest(data);return json.loads(data)
    hp=report('historical-fixture-publication-v2');pr=report('historical-pr-publication-v1');alt=report('fixture-publication-alternatives-v2');ap=report('fixture-publication-v2');aa=report('additional-fixture-audit-v1')
    if pr['parent_publication_sha256']!=inputs['historical-fixture-publication-v2'] or alt['parent_publication_report_sha256']!=inputs['fixture-publication-v2']:raise ValueError('parent report mismatch')
    if alt['fixture_audit_sha256']!=inputs['additional-fixture-audit-v1']:raise ValueError('additional audit mismatch')
    audit_bytes,cs=historical.candidates(base/'fixture-history-audit-v1',base/'raw-fixture-history-v1',base/'fixtures-git-provenance')
    if digest(audit_bytes)!=pr['fixture_audit_sha256'] or digest(audit_bytes)!=hp['fixture_audit_sha256']:raise ValueError('historical audit mismatch')
    by_key={(c['season'],c['gw']):c for c in cs};rows=[]
    items=json.loads(checked(base/'historical-pr-publication-v1/selected_calendars.json',pr['selected_sha256']))
    for r in items:
        c=by_key[(r['season'],r['gw'])];h=r['archive_hour']
        if r['evidence_type']=='PushEvent':
            root=base/'historical-fixture-publication-v2';hour=json.loads(checked(root/'hours'/(h+'.json'),hp['hour_report_sha256'][h]));historical.validate_event_projection(root,hour);proof=historical.witness(c,hour,base/'fixtures-git-provenance')
        elif r['evidence_type']=='PullRequestEvent':
            root=base/'historical-pr-publication-v1';checked(root/'hours'/(h+'.json'),pr['hour_report_sha256'][h]);hour=merged.capture(root,h,True);proof=merged.witness(c,hour,base/'fixtures-git-provenance')
        else:raise ValueError('unknown evidence type')
        if proof is None or any(r.get(k)!=v for k,v in proof.items()) or r['normalized_sha256']!=c['normalized_sha256']:raise ValueError('historical proof mismatch')
        rows.append(dict(season=c['season'],gw=c['gw'],deadline=c['deadline'],repository=historical.REPOSITORY,source_committer_at=c['committer_at'],available_at=proof['available_at'],normalized_sha256=c['normalized_sha256'],object_root='fixture-history-audit-v1',proof=proof))
    versions=json.loads(checked(base/'additional-fixture-audit-v1/versions.json',aa['artifacts']['versions.json']));versions={v['revision']:v for v in versions if v['main_series']}
    raw=json.loads(checked(base/'raw-additional-fixture-history-v1/manifest.json',aa['source_manifest_sha256']))
    items=json.loads(checked(base/'fixture-publication-alternatives-v2/selected_calendars.json',alt['artifacts']['selected_calendars.json']))
    for r in items:
        p=r['proof'];c=verify_candidate(r,versions[p['commit']],raw,base/'raw-additional-fixture-history-v1',base/'additional-fixture-audit-v1',base/'schwetche-git-provenance')
        if r['evidence_origin']=='G28':root=base/'fixture-publication-v2';descriptor=ap
        elif r['evidence_origin']=='G29':root=base/'fixture-publication-alternatives-v2';descriptor=alt
        else:raise ValueError('unknown additional evidence origin')
        h=p['archive_hour'];hour=json.loads(checked(root/'hours'/(h+'.json'),descriptor['hour_report_sha256'][h]));additional.validate_event_projection(root,hour);proof=additional.witness(c,hour,base/'schwetche-git-provenance')
        if any(p.get(k)!=v for k,v in proof.items()) or c['normalized_sha256']!=r['normalized_sha256']:raise ValueError('additional proof mismatch')
        rows.append(dict(season='2025-26',gw=c['gw'],deadline=c['deadline'],repository=additional.REPOSITORY,source_committer_at=c['committer_at'],available_at=proof['available_at'],normalized_sha256=c['normalized_sha256'],object_root='additional-fixture-audit-v1',proof=proof))
    selected=choose(rows);coverage={}
    for r in selected:
        fixtures=json.loads(gzip.decompress(checked(base/r['object_root']/'objects'/r['normalized_sha256'],r['normalized_sha256'])))
        r['nominal_commit_age_hours']=(aware(r['deadline'])-aware(r['source_committer_at'])).total_seconds()/3600
        r['future_fixture_observations']=sum(f['kickoff_time'] is not None and aware(f['kickoff_time'])>aware(r['deadline']) for f in fixtures)
        s=coverage.setdefault(r['season'],dict(deadlines=0,within48h=0,max_nominal_age_hours=0,future_fixture_observations=0))
        s['deadlines']+=1;s['within48h']+=r['nominal_commit_age_hours']<=48;s['max_nominal_age_hours']=max(s['max_nominal_age_hours'],r['nominal_commit_age_hours']);s['future_fixture_observations']+=r['future_fixture_observations']
    keys={(r['season'],r['gw']) for r in selected};missing=[dict(season=c['season'],gw=c['gw']) for c in cs if (c['season'],c['gw']) not in keys]
    out.mkdir(parents=True,exist_ok=True);payload=(json.dumps(selected,indent=2)+'\n').encode();(out/'selected_calendars.json').write_bytes(payload)
    result=dict(version='calendar-publication-selection-v1',input_report_sha256=inputs,implementation_sha256=digest(Path(__file__).read_bytes()),expected_deadlines=len(cs),selected_deadlines=len(selected),coverage=coverage,missing=missing,selected_sha256=digest(payload),production_changed=False,training_admitted=False,limitations=['commit_age_is_not_API_capture_age','whole_calendar_selected_from_one_source','publication_does_not_guarantee_schedule_freshness_or_complete_replay'])
    (out/'report.json').write_text(json.dumps(result,indent=2)+'\n');return result


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--base-root',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args();print(json.dumps(build(a.base_root,a.out),indent=2))


if __name__=='__main__':main()
