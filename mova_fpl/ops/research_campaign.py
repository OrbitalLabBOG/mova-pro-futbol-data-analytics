"""Read-only progress across independently imported runs; never an acceptance gate."""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from mova_fpl.ops.db import sha256_json
from mova_fpl.ops.research_quality import claim_fresh


def _time(value):
    value = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if value.tzinfo is None:
        raise ValueError('timezone required')
    return value


def _identity(row):
    return tuple(row.get(k) for k in ('player_name','team','position','official_status',
                                      'official_chance_next','official_news'))


def progress(config, db, cycle_id=None, *, now=None):
    from mova_fpl.ops.research_continuation import supported_policy
    current = now or datetime.now(timezone.utc)
    cycle_id = cycle_id or (db.status().get('cycle') or {}).get('cycle_id')
    manifest = db.latest_cycle_manifest(cycle_id) if cycle_id else None
    focus = {int(r['element']): r for r in (manifest or {}).get('research_summary',{}).get('focus',[])}
    report = {'schema':'mova-research-campaign-v1','cycle_id':cycle_id,'generated_at':current.isoformat(),
              'status':'pending','required_subjects':len(focus),'verified_subjects':0,
              'pending_subjects':sorted(focus),'subjects':[], 'runs':[],
              'runtime_mutated':False,'permits_execution':False,'acceptance_eligible':False}
    if not focus:
        return report
    if _time(manifest['as_of_at']) > current:
        report['status'] = 'future_manifest'
        return report
    deadline = _time(manifest['deadline_at'])
    with db.connect(readonly=True) as con:
        runs = [dict(r) for r in con.execute(
            "SELECT * FROM research_runs r WHERE cycle_id=? AND status='imported' "
            "AND NOT EXISTS (SELECT 1 FROM audit_events a WHERE a.subject_id=r.research_run_id "
            "AND a.event_type IN ('research_experiment_enqueued','research_experiment_completed')) "
            "ORDER BY imported_at DESC,queued_at DESC,research_run_id DESC",(cycle_id,))]
        docs = [dict(r) for r in con.execute(
            'SELECT d.* FROM research_documents d JOIN research_runs r ON r.research_run_id=d.research_run_id '
            'WHERE r.cycle_id=? AND r.status=\'imported\' AND d.fetch_status=\'verified\'',(cycle_id,))]
        signals=[dict(r) for r in con.execute(
            "SELECT s.* FROM research_signals s WHERE cycle_id=? AND validation_status='accepted'",
            (cycle_id,))]
        conflicts=con.execute("SELECT COUNT(*) FROM research_conflicts WHERE cycle_id=? AND status='unresolved'",
                              (cycle_id,)).fetchone()[0]
    documents = {(d['research_run_id'],d['source_url']):d for d in docs}
    sealed = {}
    def valid_document(row):
        if not row:return False
        key=row['document_id']
        if key not in sealed:
            try:
                path=Path(row['artifact_path'])
                if (not path.resolve().is_relative_to(config.research_root.resolve())
                        or not path.is_file() or path.stat().st_size>1_048_576
                        or hashlib.sha256(path.read_bytes()).hexdigest()!=row['artifact_sha256']):
                    raise ValueError('invalid sealed evidence')
                body=json.loads(path.read_text())
                sealed[key]=(body.get('publication_date_verified') is True
                    and body.get('research_run_id')==row['research_run_id']
                    and body.get('document_id')==key
                    and body.get('source_url')==row['source_url']
                    and body.get('excerpt_sha256')==row['excerpt_sha256']
                    and _time(row['observed_at'])<=min(current,deadline)
                    and claim_fresh(claim_type='coverage',published_at=row['published_at'],observed=current))
            except (OSError,ValueError,TypeError,KeyError):sealed[key]=False
        return sealed[key]
    selected={}
    for run in runs:
        try:
            if _time(run['imported_at'])>current:continue
            path=Path(run['request_path'])
            if not path.is_file():path=config.research_root/'archive'/path.name
            if not path.resolve().is_relative_to(config.research_root.resolve()) or path.stat().st_size>1_048_576:continue
            request=json.loads(path.read_text())
            unsigned={k:v for k,v in request.items() if k!='request_sha256'}
            if (not supported_policy(request.get('completion_policy')) or request.get('experiment')
                    or sha256_json(unsigned)!=run['request_sha256']
                    or request.get('request_sha256')!=run['request_sha256']
                    or _time(request['manifest']['deadline_at'])!=deadline):continue
            original={int(r['element']):r for r in request['manifest']['research_summary']['focus']}
            coverage=json.loads(run['coverage_json'])
            report['runs'].append(run['research_run_id'])
            for row in coverage.get('subjects',[]):
                element=int(row['player_element'])
                if (element not in focus or element in selected or row['status']=='not_checked'
                        or _identity(original.get(element,{}))!=_identity(focus[element])):continue
                sources=[documents.get((run['research_run_id'],url)) for url in row.get('source_urls',[])]
                verified=(row.get('evidence_verified') is True and any(valid_document(d) for d in sources))
                # A newer explicit uncertainty invalidates an older positive assessment.
                material_fresh = row['status'] != 'material_signal' or any(
                    signal['research_run_id']==run['research_run_id']
                    and signal['player_element']==element
                    and signal['conflict_status']!='unresolved'
                    and _time(signal['expires_at'])>current
                    and claim_fresh(claim_type=signal['claim_type'],published_at=signal['published_at'],observed=current)
                    for signal in signals)
                selected[element]={'player_element':element,'evidence_verified':verified,
                    'resolved':verified and row['status']!='unresolved' and material_fresh,
                    'status':row['status'],'research_run_id':run['research_run_id'],
                    'verified_at':run['imported_at'],'document_ids':[d['document_id'] for d in sources if valid_document(d)]}
        except (OSError,ValueError,TypeError,KeyError):continue
    report['subjects']=[selected.get(e,{'player_element':e,'evidence_verified':False,'resolved':False,'status':'not_checked'}) for e in sorted(focus)]
    report['pending_subjects']=[r['player_element'] for r in report['subjects'] if not r['resolved']]
    report['pending_evidence_subjects']=[r['player_element'] for r in report['subjects'] if not r['evidence_verified']]
    report['open_questions']=[r['player_element'] for r in report['subjects'] if r['evidence_verified'] and not r['resolved']]
    report['investigation_status']=('partial' if report['pending_evidence_subjects'] else
        ('complete_with_uncertainty' if report['open_questions'] or conflicts else 'complete'))
    report['completed_subjects']=len(focus)-len(report['pending_subjects'])
    report['verified_subjects']=sum(r['evidence_verified'] for r in report['subjects'])
    report['coverage_ratio']=report['verified_subjects']/len(focus)
    report['unresolved_conflicts']=conflicts
    report['status']='partial' if report['pending_subjects'] else ('conflicts_pending' if conflicts else 'complete')
    report['groups']={}
    for label,reason in [('current_squad','current_squad'),('model_candidates','top_projection_candidate')]:
        ids={e for e,r in focus.items() if reason in r.get('focus_reason',[])}
        report['groups'][label]={'required':len(ids),'verified':sum(r['evidence_verified'] for r in report['subjects'] if r['player_element'] in ids),
                                'completed':sum(r['resolved'] for r in report['subjects'] if r['player_element'] in ids)}
    report['content_sha256']=sha256_json(report)
    return report
