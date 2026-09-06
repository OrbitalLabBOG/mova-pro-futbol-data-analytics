"""Audit exporter provenance and past-only clock concordance; do not infer publication or repair dates."""
from __future__ import annotations
import argparse
import ast
from collections import Counter
import csv
from datetime import datetime,timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from experiments.data_ground_truth.bootstrap_time import aware,parse_log
from experiments.data_ground_truth.fixture_commit_plan import git
from experiments.data_ground_truth.raw import capture,digest
from experiments.data_ground_truth.training_dataset import checked


def inspect_code(data):
    try:tree=ast.parse(data)
    except SyntaxError as exc:return dict(parseable=False,syntax_error_line=exc.lineno,infer_gameweek_uses_utc=None,kickoff_literal_references=None,matches_table_read=None)
    inferred=False
    for node in ast.walk(tree):
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name=='infer_gameweek':
            inferred=any(isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute) and call.func.attr=='to_datetime'
                and any(k.arg=='utc' and isinstance(k.value,ast.Constant) and k.value.value is True for k in call.keywords) for call in ast.walk(node))
    return dict(parseable=True,infer_gameweek_uses_utc=inferred,
        kickoff_literal_references=sum(isinstance(n,ast.Constant) and n.value=='kickoff_time' for n in ast.walk(tree)),
        matches_table_read=any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='fetch_all_rows'
            and any(isinstance(a,ast.Constant) and a.value=='matches' for a in n.args) for n in ast.walk(tree)))


def past_comparison(raw,reference,cutoff):
    parsed=datetime.fromisoformat(raw.replace('Z','+00:00'))
    if parsed.tzinfo is not None:return None
    assumed=parsed.replace(tzinfo=timezone.utc);actual=aware(reference);boundary=aware(cutoff)
    if assumed>=boundary or actual>=boundary:return None
    return dict(delta_seconds=int((assumed-actual).total_seconds()),
        reference_uk_offset_seconds=int(actual.astimezone(ZoneInfo('Europe/London')).utcoffset().total_seconds()))


def build(repo:Path,export_log:Path,code_root:Path,tree_root:Path,fixture_root:Path,teams_root:Path,out:Path):
    logs=export_log.read_bytes();changes=parse_log(logs.decode())['scripts/export_data.py'];codes={};code_rows=[]
    for c in sorted(changes,key=lambda c:(c['committer_at'],c['commit'])):
        if c['status']=='D':continue
        if c['status'] not in ('A','M'):raise ValueError('unsupported exporter change')
        record=capture(code_root,'olbauday/FPL-Core-Insights',c['commit'],'scripts/export_data.py')
        data=checked(code_root/'objects'/record['sha256'],record['sha256'])
        if hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()!=c['new_blob']:raise ValueError('exporter Git blob mismatch')
        evidence=inspect_code(data);codes[c['new_blob']]=evidence
        code_rows.append(dict(revision=c['commit'],committer_at=c['committer_at'],git_blob=c['new_blob'],source_sha256=record['sha256'],**evidence))
    source_bytes=(tree_root/'report.json').read_bytes();source=json.loads(source_bytes)
    calendars=json.loads(checked(tree_root/'calendars.json',source['artifacts']['calendars.json']))
    fixture_report_bytes=(fixture_root/'report.json').read_bytes();fixture_report=json.loads(fixture_report_bytes)
    versions=json.loads(checked(fixture_root/'versions.json',fixture_report['artifacts']['versions.json']))
    reference=max((r for r in versions if r['season']=='2025-26'),key=lambda r:r['committer_at'])
    fixtures=json.loads(gzip.decompress(checked(fixture_root/'objects'/reference['normalized_sha256'],reference['normalized_sha256'])))
    teams_manifest_bytes=(teams_root/'manifest.json').read_bytes();manifest=json.loads(teams_manifest_bytes)
    record=next(r for r in manifest['records'] if r['repository']=='vaastav/Fantasy-Premier-League' and r['path']=='data/2025-26/teams.csv')
    teams=list(csv.DictReader(io.StringIO(checked(teams_root/'objects'/record['sha256'],record['sha256']).decode())))
    team_codes={int(r['id']):int(r['code']) for r in teams}
    if len(team_codes)!=len(teams) or len(set(team_codes.values()))!=len(teams):raise ValueError('ambiguous team codes')
    reference_pairs={(team_codes[r['team_h']],team_codes[r['team_a']]):r for r in fixtures}
    if len(reference_pairs)!=len(fixtures):raise ValueError('ambiguous reference fixture pair')
    rows=[];comparisons=[]
    for calendar in calendars:
        if calendar['status']!='audited':continue
        revision=calendar['revision']
        blobline=git(repo,'ls-tree',revision,'--','scripts/export_data.py')
        evidence=codes.get(blobline.split()[2]) if blobline else None
        data=json.loads(gzip.decompress(checked(tree_root/'objects'/calendar['normalized_sha256'],calendar['normalized_sha256'])))
        pair_counts=Counter((r['home_team_code'],r['away_team_code']) for r in data)
        stats=Counter();offsets=Counter()
        for r in data:
            pair=(r['home_team_code'],r['away_team_code']);ref=reference_pairs.get(pair)
            if not ref or pair_counts[pair]!=1:stats['unresolved_team_pair']+=1;continue
            stats['matched_team_pair']+=1
            if r['schedule_conflict']:stats['schedule_conflict_excluded']+=1;continue
            for raw in r['raw_kickoff_values']:
                if ref['kickoff_time'] is None:continue
                result=past_comparison(raw,ref['kickoff_time'],calendar['source_committer_at'])
                if result is None:continue
                offsets[str(result['delta_seconds'])]+=1;stats['past_naive_comparisons']+=1
                if result['delta_seconds']==0:stats['exact_utc_hypothesis_matches']+=1
                comparisons.append(dict(gw=calendar['gw'],provider_match_id=r['provider_match_id'],reference_fixture=ref['id'],
                    source_raw_time=raw,reference_time=ref['kickoff_time'],source_revision=revision,**result))
        rows.append(dict(gw=calendar['gw'],source_revision=revision,exporter_evidence=evidence,stats=dict(stats),delta_seconds=dict(offsets)))
    out.mkdir(parents=True,exist_ok=True);artifacts={}
    for name,value in [('exporters.json',code_rows),('deadlines.json',rows),('past_comparisons.json',comparisons)]:
        payload=(json.dumps(value,indent=2)+'\n').encode();(out/name).write_bytes(payload);artifacts[name]=digest(payload)
    report=dict(version='core-clock-evidence-v2',export_log_sha256=digest(logs),source_tree_report_sha256=digest(source_bytes),
        fixture_reference_report_sha256=digest(fixture_report_bytes),fixture_reference_revision=reference['revision'],
        teams_manifest_sha256=digest(teams_manifest_bytes),teams_sha256=record['sha256'],implementation_sha256=digest(Path(__file__).read_bytes()),
        exporter_versions=len(code_rows),unparseable_exporter_versions=sum(not r['parseable'] for r in code_rows),deleted_exporter_versions=sum(c['status']=='D' for c in changes),
        first_utc_inference_commit=next((r for r in code_rows if r['infer_gameweek_uses_utc']),None),
        audited_deadlines=len(rows),deadlines_with_exporter=sum(r['exporter_evidence'] is not None for r in rows),
        past_naive_comparisons=len(comparisons),exact_utc_hypothesis_matches=sum(r['delta_seconds']==0 for r in comparisons),
        delta_seconds=dict(Counter(str(r['delta_seconds']) for r in comparisons)),
        reference_uk_offsets=dict(Counter(str(r['reference_uk_offset_seconds']) for r in comparisons)),artifacts=artifacts,
        normalization_promoted=False,publication_proven=False,production_changed=False,
        limitations=['team_pair_matching_is_not_fixture_identity_proof_and_may_cross_competitions','exporter_consumer_assumption_is_not_producer_clock_proof','final_fixture_reference_used_only_for_retrospective_past_match_diagnostic',
        'comparisons_repeat_matches_across_snapshots','no_future_date_or_training_admission_changed'])
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('repo','export-log','code-root','tree-root','fixture-root','teams-root','out'):ap.add_argument('--'+name,type=Path,required=True)
    a=ap.parse_args();print(json.dumps(build(a.repo,a.export_log,a.code_root,a.tree_root,a.fixture_root,a.teams_root,a.out),indent=2))


if __name__=='__main__':main()
