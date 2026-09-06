"""Measure fixture-history changes and nominal predeadline coverage without admitting time."""
from __future__ import annotations
import argparse
from collections import Counter
import csv
from decimal import Decimal,InvalidOperation
import gzip
import io
import json
from pathlib import Path

from experiments.data_ground_truth.bootstrap_time import aware
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked


def integer(value,nullable=False):
    if value=='':
        if nullable:return None
        raise ValueError('missing fixture integer')
    try:d=Decimal(value)
    except InvalidOperation as exc:raise ValueError('invalid fixture integer') from exc
    if not d.is_finite() or d!=d.to_integral_value() or d<=0:raise ValueError('invalid fixture integer')
    return int(d)


def boolean(value):
    if value=='':return None
    if value in ('True','true'):return True
    if value in ('False','false'):return False
    raise ValueError('invalid fixture boolean')


def parse(data):
    reader=csv.DictReader(io.StringIO(data.decode('utf-8-sig')))
    required={'id','event','kickoff_time','team_h','team_a'}
    if not reader.fieldnames or not required.issubset(reader.fieldnames) or len(reader.fieldnames)!=len(set(reader.fieldnames)):
        raise ValueError('fixture schema mismatch')
    rows=[];ids=set();pairs=set()
    for source in reader:
        if None in source or any(v is None for v in source.values()):raise ValueError('ragged fixture CSV')
        r={k:integer(source[k],nullable=k=='event') for k in ('id','event','team_h','team_a')}
        if r['id'] in ids or r['team_h']==r['team_a'] or (r['team_h'],r['team_a']) in pairs:raise ValueError('duplicate/invalid fixture identity')
        ids.add(r['id']);pairs.add((r['team_h'],r['team_a']))
        r['kickoff_time']=aware(source['kickoff_time']).isoformat() if source['kickoff_time'] else None
        if 'code' in source:r['code']=integer(source['code'],nullable=True)
        for k in ('finished','finished_provisional','started','provisional_start_time'):
            r[k+'_present']=k in source
            if k in source:r[k]=boolean(source[k])
        for k in ('team_h_difficulty','team_a_difficulty'):
            r[k+'_present']=k in source
            if k in source:r[k]=integer(source[k],nullable=True)
        rows.append(r)
    if not rows:raise ValueError('empty fixture CSV')
    return sorted(rows,key=lambda r:r['id'])


def build(root:Path,selection_root:Path,out:Path):
    manifest_bytes=(root/'manifest.json').read_bytes();manifest=json.loads(manifest_bytes)
    if manifest['errors'] or len(manifest['records'])!=manifest['expected_versions']:raise ValueError('incomplete fixture acquisition')
    selection_bytes=(selection_root/'report.json').read_bytes();selection=json.loads(selection_bytes)
    candidates=json.loads(checked(selection_root/'nominal_deadline_candidates.json',selection['artifacts']['nominal_deadline_candidates.json']))
    out.mkdir(parents=True,exist_ok=True);(out/'objects').mkdir(exist_ok=True)
    versions=[];errors=[];changes=[];previous={};seasons={}
    for r in manifest['records']:
        try:rows=parse(checked(root/'objects'/r['sha256'],r['sha256']))
        except (ValueError,KeyError,UnicodeError) as exc:
            errors.append(dict(season=r['season'],revision=r['revision'],error=str(exc)));continue
        payload=gzip.compress((json.dumps(rows,sort_keys=True,separators=(',',':'))+'\n').encode(),mtime=0)
        sha=digest(payload);(out/'objects'/sha).write_bytes(payload)
        current={x['id']:x for x in rows};before=previous.get(r['season'])
        if before:
            for fid in sorted(set(current)&set(before['rows'])):
                a,b=before['rows'][fid],current[fid]
                for field in ('event','kickoff_time','team_h','team_a','code'):
                    if a.get(field)!=b.get(field):changes.append(dict(season=r['season'],fixture=fid,field=field,before=a.get(field),after=b.get(field),
                        previous_revision=before['revision'],revision=r['revision'],source_committer_at=r['committer_at']))
            if set(current)!=set(before['rows']):changes.append(dict(season=r['season'],field='fixture_population',added=sorted(set(current)-set(before['rows'])),
                removed=sorted(set(before['rows'])-set(current)),revision=r['revision'],source_committer_at=r['committer_at']))
        previous[r['season']]=dict(rows=current,revision=r['revision'])
        record=dict(season=r['season'],revision=r['revision'],committer_at=r['committer_at'],source_sha256=r['sha256'],
            normalized_sha256=sha,fixtures=len(rows),unassigned_events=sum(x['event'] is None for x in rows),
            unknown_kickoffs=sum(x['kickoff_time'] is None for x in rows),available_at=None,eligible_predeadline=False)
        versions.append(record)
        s=seasons.setdefault(r['season'],dict(versions=0,row_counts=set(),first_commit=r['committer_at'],last_commit=r['committer_at']))
        s['versions']+=1;s['row_counts'].add(len(rows));s['last_commit']=r['committer_at']
    nominal=[]
    for c in candidates:
        prior=[v for v in versions if v['season']==c['season'] and aware(v['committer_at'])<aware(c['deadline'])]
        row=dict(season=c['season'],gw=c['gw'],deadline=c['deadline'],available_at=None,eligible_predeadline=False)
        if prior:
            v=max(prior,key=lambda v:(aware(v['committer_at']),v['revision']))
            row.update(revision=v['revision'],source_sha256=v['source_sha256'],normalized_sha256=v['normalized_sha256'],
                source_committer_at=v['committer_at'],nominal_age_hours=(aware(c['deadline'])-aware(v['committer_at'])).total_seconds()/3600)
        else:row['status']='no_prior_commit'
        nominal.append(row)
    for season,s in seasons.items():
        s['row_counts']=sorted(s['row_counts']);selected=[r for r in nominal if r['season']==season]
        ages=[r['nominal_age_hours'] for r in selected if 'nominal_age_hours' in r]
        s.update(compared_deadlines=len(selected),with_prior_commit=len(ages),within_48h=sum(a<=48 for a in ages),within_7d=sum(a<=168 for a in ages),
                 max_nominal_age_hours=max(ages) if ages else None)
    artifacts={}
    for name,value in [('versions.json',versions),('changes.json',changes),('nominal_candidates.json',nominal),('errors.json',errors)]:
        payload=(json.dumps(value,indent=2)+'\n').encode();(out/name).write_bytes(payload);artifacts[name]=digest(payload)
    report=dict(version='fixture-history-audit-v1',manifest_sha256=digest(manifest_bytes),selection_report_sha256=digest(selection_bytes),
        implementation_sha256=digest(Path(__file__).read_bytes()),versions=len(versions),errors=len(errors),seasons=seasons,
        observed_field_changes=dict(Counter(r['field'] for r in changes)),artifacts=artifacts,
        eligible_predeadline=False,eligible_training=False,production_changed=False,
        limitations=['Git_time_is_source_claim_only','old_calendar_is_not_guaranteed_latest_known_calendar','no_fixture_or_team_ID_mapping_across_seasons'])
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('root','selection-root','out'):ap.add_argument('--'+name,type=Path,required=True)
    a=ap.parse_args();r=build(a.root,a.selection_root,a.out);print(json.dumps(r,indent=2))
    if r['errors']:raise SystemExit(1)


if __name__=='__main__':main()
