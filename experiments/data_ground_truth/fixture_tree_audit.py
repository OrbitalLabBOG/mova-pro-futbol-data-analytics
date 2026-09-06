"""Audit source-coherent fixture trees, including missing and conflicting schedule values."""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
import csv
from datetime import datetime
import gzip
import io
import json
from pathlib import Path

from experiments.data_ground_truth.bootstrap_time import aware
from experiments.data_ground_truth.fixture_history_audit import integer
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked


def parse(data,source):
    reader=csv.DictReader(io.StringIO(data.decode('utf-8-sig')))
    mapping=dict(provider_match_id='match_id',provider_gameweek='gameweek',home_team_code='home_team',away_team_code='away_team',kickoff_time='kickoff_time') if source=='core' else dict(provider_match_id='fpl_id',provider_gameweek='gameweek',home_team_code='team_h_opta_id',away_team_code='team_a_opta_id',kickoff_time='kickoff_time')
    required=set(mapping.values()) if source=='core' else {'fpl_id','gameweek','kickoff_time'}
    if not reader.fieldnames or len(reader.fieldnames)!=len(set(reader.fieldnames)) or not required.issubset(reader.fieldnames):raise ValueError('complement CSV schema mismatch')
    rows=[];ids=set()
    for raw in reader:
        if None in raw or any(v is None for v in raw.values()):raise ValueError('ragged complement CSV')
        row={k:raw.get(v,'') for k,v in mapping.items()}
        if not row['provider_match_id'] or row['provider_match_id'] in ids:raise ValueError('ambiguous provider match id')
        ids.add(row['provider_match_id'])
        for k in ('provider_gameweek','home_team_code','away_team_code'):row[k]=integer(row[k],nullable=True)
        if row['home_team_code'] is not None and row['home_team_code']==row['away_team_code']:raise ValueError('same-team fixture')
        row['kickoff_time_raw']=row['kickoff_time']
        parsed=datetime.fromisoformat(row['kickoff_time'].replace('Z','+00:00')) if row['kickoff_time'] else None
        row['kickoff_timezone_unknown']=parsed is not None and parsed.tzinfo is None
        row['kickoff_time']=aware(row['kickoff_time']).isoformat() if parsed is not None and parsed.tzinfo is not None else None
        row['source_team_ids']={k:raw[k] for k in ('team_h_fpl_id','team_a_fpl_id') if k in raw}
        rows.append(row)
    return rows


def consolidate(components):
    grouped=defaultdict(list)
    for path,rows in components:
        for r in rows:grouped[r['provider_match_id']].append((path,r))
    result=[];conflicts=[]
    for mid,observations in sorted(grouped.items()):
        row=dict(provider_match_id=mid,source_paths=sorted(p for p,_ in observations));bad={}
        for k in ('provider_gameweek','home_team_code','away_team_code','kickoff_time'):
            values={r[k] for _,r in observations if r[k] is not None}
            if len(values)>1:bad[k]=sorted(values)
            row[k]=next(iter(values)) if len(values)==1 else None
        if bad:conflicts.append(dict(provider_match_id=mid,conflicts=bad,source_paths=row['source_paths']))
        row['raw_kickoff_values']=sorted({r.get('kickoff_time_raw','') for _,r in observations if r.get('kickoff_time_raw')})
        row['has_unknown_kickoff_timezone']=any(r.get('kickoff_timezone_unknown',False) for _,r in observations)
        row['source_team_id_observations']=[r['source_team_ids'] for _,r in observations if r.get('source_team_ids')]
        row['schedule_conflict']=bool(bad);result.append(row)
    return result,conflicts


def build(root:Path,plan_root:Path,out:Path):
    raw=(root/'manifest.json').read_bytes();manifest=json.loads(raw)
    if manifest['errors'] or len(manifest['records'])!=manifest['expected_versions']:raise ValueError('incomplete complement acquisition')
    plan_bytes=(plan_root/'report.json').read_bytes();plan=json.loads(plan_bytes)
    if plan['repository']!=manifest['repository'] or plan['pinned_revision']!=manifest['pinned_revision'] or plan['git_log_sha256']!=manifest['git_log_sha256']:raise ValueError('complement plan provenance mismatch')
    trees=json.loads(checked(plan_root/'trees.json',plan['trees_sha256']))
    by_blob={};parse_cache={};file_errors=[];schema_counts=Counter()
    for r in manifest['records']:
        if r['git_blob'] in by_blob and by_blob[r['git_blob']]['sha256']!=r['sha256']:raise ValueError('Git blob content conflict')
        by_blob[r['git_blob']]=r
        if r['sha256'] in parse_cache:continue
        try:parse_cache[r['sha256']]=parse(checked(root/'objects'/r['sha256'],r['sha256']),manifest['source'])
        except (ValueError,KeyError,UnicodeError) as exc:
            parse_cache[r['sha256']]=None;file_errors.append(dict(source_sha256=r['sha256'],path=r['path'],error=str(exc)))
    out.mkdir(parents=True,exist_ok=True);(out/'objects').mkdir(exist_ok=True)
    rows=[];all_conflicts=[]
    for t in trees:
        context={k:t[k] for k in ('season','gw','deadline')}
        if 'entries' not in t:rows.append(dict(context,status='no_prior_commit'));continue
        components=[];bad=[]
        for e in t['entries']:
            r=by_blob.get(e['git_blob'])
            if not r or parse_cache[r['sha256']] is None:bad.append(e['path']);continue
            components.append((e['path'],parse_cache[r['sha256']]))
        if bad:rows.append(dict(context,revision=t['revision'],status='unusable_component',paths=bad));continue
        fixtures,conflicts=consolidate(components)
        data=gzip.compress((json.dumps(fixtures,sort_keys=True,separators=(',',':'))+'\n').encode(),mtime=0);sha=digest(data);(out/'objects'/sha).write_bytes(data)
        for conflict in conflicts:all_conflicts.append(dict(context,revision=t['revision'],**conflict))
        known=[r for r in fixtures if r['kickoff_time'] is not None and not r['schedule_conflict']]
        upcoming=[r for r in fixtures if r['provider_gameweek'] is not None and r['provider_gameweek']>=t['gw']]
        row=dict(context,revision=t['revision'],source_committer_at=t['source_committer_at'],nominal_commit_age_hours=t['nominal_commit_age_hours'],
            status='audited',files=len(components),provider_fixtures=len(fixtures),schedule_conflicts=len(conflicts),
            unknown_kickoff_timezone_rows=sum(r['has_unknown_kickoff_timezone'] for r in fixtures),
            known_kickoffs=len(known),known_kickoffs_after_commit=sum(aware(r['kickoff_time'])>aware(t['source_committer_at']) for r in known),
            current_or_later_raw_kickoffs=sum(bool(r['raw_kickoff_values']) for r in upcoming),
            current_or_later_provider_gameweek_rows=len(upcoming),current_or_later_known_kickoffs=sum(r['kickoff_time'] is not None and not r['schedule_conflict'] for r in upcoming),
            unknown_team_codes=sum(r['home_team_code'] is None or r['away_team_code'] is None for r in fixtures),
            normalized_sha256=sha,available_at=None,eligible_predeadline=False)
        rows.append(row)
    artifacts={}
    for name,value in [('calendars.json',rows),('conflicts.json',all_conflicts),('file_errors.json',file_errors)]:
        data=(json.dumps(value,indent=2)+'\n').encode();(out/name).write_bytes(data);artifacts[name]=digest(data)
    audited=[r for r in rows if r['status']=='audited']
    report=dict(version='fixture-tree-audit-v1',source=manifest['source'],manifest_sha256=digest(raw),plan_report_sha256=digest(plan_bytes),
        implementation_sha256=digest(Path(__file__).read_bytes()),distinct_source_objects=len(parse_cache),file_errors=len(file_errors),
        deadlines=len(rows),audited_calendars=len(audited),provider_fixture_counts=sorted({r['provider_fixtures'] for r in audited}),
        unknown_kickoff_timezone_rows=sum(r['unknown_kickoff_timezone_rows'] for r in audited),
        schedule_conflict_observations=len(all_conflicts),known_kickoffs_after_commit=sum(r['known_kickoffs_after_commit'] for r in audited),
        current_or_later_raw_kickoffs=sum(r['current_or_later_raw_kickoffs'] for r in audited),
        current_or_later_provider_gameweek_rows=sum(r['current_or_later_provider_gameweek_rows'] for r in audited),
        current_or_later_known_kickoffs=sum(r['current_or_later_known_kickoffs'] for r in audited),artifacts=artifacts,
        eligible_predeadline=False,eligible_training=False,production_changed=False,
        limitations=['provider_gameweek_is_not_yet_verified_as_FPL_gameweek','nonnull_union_is_limited_to_files_in_the_same_verified_Git_tree',
                     'conflicting_schedule_values_are_not_silently_selected','Git_time_is_not_verified_publication_time'])
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('root','plan-root','out'):ap.add_argument('--'+name,type=Path,required=True)
    a=ap.parse_args();print(json.dumps(build(a.root,a.plan_root,a.out),indent=2))


if __name__=='__main__':main()
