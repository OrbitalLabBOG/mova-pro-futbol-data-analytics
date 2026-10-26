"""Prospective campaign acceptance; no legacy cohort is reinterpreted or promoted."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from mova_fpl.ops.db import sha256_json
from mova_fpl.ops.research_acceptance import _time, current_contract
from mova_fpl.ops.research_campaign import progress


def _sealed_request(config, run):
    path = Path(run['request_path'])
    if not path.is_file():
        path = config.research_root / 'archive' / path.name
    if (not path.resolve().is_relative_to(config.research_root.resolve())
            or path.stat().st_size > 1_048_576):
        raise ValueError('invalid request path')
    value = json.loads(path.read_text())
    if (value.get('request_sha256') != run['request_sha256']
            or value.get('research_run_id') != run['research_run_id']
            or value.get('cycle_id') != run['cycle_id']
            or sha256_json({k: v for k, v in value.items() if k != 'request_sha256'}) != run['request_sha256']):
        raise ValueError('request hash mismatch')
    return value


def slot_report(db, config, manifest, slot, *, now):
    cutoff = min(now, _time(slot['deadline_at']))
    expired = now >= _time(slot['deadline_at'])
    reasons, run_ids, slots_seen = [], [], set()
    with db.connect(readonly=True) as con:
        runs = [dict(r) for r in con.execute(
            "SELECT r.* FROM research_runs r WHERE cycle_id=? AND NOT EXISTS "
            "(SELECT 1 FROM audit_events a WHERE a.subject_id=r.research_run_id "
            "AND a.event_type IN ('research_experiment_enqueued','research_experiment_completed')) "
            "ORDER BY queued_at,research_run_id", (slot['cycle_id'],))]
        for run in runs:
            run_ids.append(run['research_run_id'])
            try:
                request = _sealed_request(config, run)
                if request.get('experiment'):
                    reasons.append('experiment_in_operational_campaign')
                if request.get('acceptance_contract') != manifest['contract']:
                    reasons.append('run_contract_drift')
                if ((request.get('manifest') or {}).get('cycle_id') != slot['cycle_id']
                        or _time((request.get('manifest') or {})['deadline_at']) != _time(slot['deadline_at'])):
                    reasons.append('cycle_deadline_drift')
                if not _time(slot['opens_at']) <= _time(run['queued_at']) < _time(slot['deadline_at']):
                    reasons.append('run_outside_preregistered_window')
                if request.get('run_kind') in {'broad', 'refresh', 'final'}:
                    seconds = (_time(slot['deadline_at']) - _time(run['queued_at'])).total_seconds()
                    kind = request['run_kind']
                    valid_window = (kind == 'broad' and seconds > 6*3600
                                    or kind == 'refresh' and 2*3600 < seconds <= 6*3600
                                    or kind == 'final' and config.research_final_cutoff_seconds < seconds <= 2*3600)
                    if not valid_window:
                        reasons.append('refresh_outside_declared_window')
                    if run['status'] == 'imported':
                        slots_seen.add(kind)
                if request.get('continuation'):
                    parent = request['continuation']['parent_run_id']
                    previous = next((r for r in runs if r['research_run_id'] == parent), None)
                    if (not previous or _time(previous['queued_at']) >= _time(run['queued_at'])
                            or previous['result_sha256'] != request['continuation']['parent_result_sha256']):
                        reasons.append('continuation_parent_invalid')
                events = list(con.execute('SELECT * FROM agent_worker_attempt_events '
                                           'WHERE subject_id=? AND subject_type=\'research\'',
                                           (run['research_run_id'],)))
                starts = [e for e in events if e['event_type'] == 'started']
                finishes = [e for e in events if e['event_type'] == 'finished']
                if len(starts) > manifest['contract']['max_attempts']:
                    reasons.append('attempt_limit_exceeded')
                if any(e['status'] == 'failed' for e in finishes) or run['status'] in {'failed', 'rejected'}:
                    reasons.append('failed_attempt_or_run')
                if any(e['request_sha256'] != run['request_sha256']
                       or e['model'] != manifest['contract']['model']
                       or not _time(slot['opens_at']) <= _time(e['occurred_at']) < _time(slot['deadline_at'])
                       for e in events):
                    reasons.append('attempt_contract_or_causality_drift')
                if run['status'] == 'imported':
                    if not _time(slot['opens_at']) <= _time(run['imported_at']) < _time(slot['deadline_at']):
                        reasons.append('result_imported_outside_window')
                    result = Path(run['result_path'])
                    if (not result.resolve().is_relative_to(config.research_root.resolve())
                            or hashlib.sha256(result.read_bytes()).hexdigest() != run['result_sha256']):
                        reasons.append('result_artifact_invalid')
                    if run['result_schema'] != manifest['contract']['release']['output_schema']:
                        reasons.append('result_schema_drift')
                    reservation = con.execute('SELECT * FROM agent_budget_reservations WHERE subject_id=?',
                                              (run['research_run_id'],)).fetchone()
                    if (not starts or {e['attempt_id'] for e in starts} != {e['attempt_id'] for e in finishes}
                            or any(e['status'] != 'succeeded' or e['input_tokens'] is None or e['output_tokens'] is None for e in finishes)
                            or not reservation or reservation['status'] != 'settled'
                            or reservation['accounting_mode'] != 'exact' or reservation['actual_tokens'] is None):
                        reasons.append('attempt_or_usage_unproven')
                    elif reservation['actual_tokens'] > manifest['contract']['budget']['job_tokens']:
                        reasons.append('budget_exceeded')
                elif expired:
                    reasons.append('run_not_terminal_before_deadline')
            except (OSError, ValueError, KeyError, TypeError):
                reasons.append('campaign_artifact_invalid')
        # Resolution after deadline cannot repair an earlier conflict.
        conflicts = con.execute("SELECT conflict_id,status FROM research_conflicts WHERE cycle_id=? "
                                "AND julianday(created_at)<=julianday(?)", (slot['cycle_id'], cutoff.isoformat())).fetchall()
        for conflict in conflicts:
            resolved = con.execute("SELECT 1 FROM audit_events WHERE subject_id=? "
                                   "AND event_type='research_conflict_resolved' "
                                   "AND julianday(occurred_at)<=julianday(?)", (conflict['conflict_id'], cutoff.isoformat())).fetchone()
            if conflict['status'] == 'unresolved' or not resolved:
                reasons.append('unresolved_conflict_at_cutoff')
    coverage = progress(config, db, slot['cycle_id'], now=cutoff, manifest_as_of=True)
    required = coverage.get('required_subjects', 0)
    checked = coverage.get('processed_subjects', 0) / required if required else 0
    verified = coverage.get('verified_subjects', 0) / required if required else 0
    if expired:
        budget = db.cost_report(config.agent_budget_policy(), season=manifest['season'], gw=slot['gw'])
        if budget['gameweek']['status'] != 'within_budget':
            reasons.append('campaign_budget_exceeded')
        if checked < .9 or verified < .8:
            reasons.append('quality_thresholds_failed')
        if not {'broad', 'refresh', 'final'} <= slots_seen:
            reasons.append('mandatory_refresh_missing')
        if not runs:
            reasons.append('not_executed')
    status = 'failed' if reasons else 'passed' if expired else 'pending'
    return {**slot, 'status': status, 'reasons': sorted(set(reasons)),
            'research_run_id': run_ids[0] if run_ids else None, 'research_run_ids': run_ids,
            'coverage_ratio': checked, 'evidence_ratio': verified,
            'pending_subjects': coverage.get('pending_subjects', []),
            'cutoff_at': cutoff.isoformat(), 'selection': 'all_operational_runs_until_deadline'}


def cohort_report(db, config, row, manifest, *, now):
    slots = [slot_report(db, config, manifest, s, now=now) for s in manifest['slots']] if config else []
    drift = config is None or manifest['contract'] != current_contract(config, campaign=True)
    if drift:
        slots = [{**s, 'status': 'failed',
                  'reasons': sorted(set(s.get('reasons', []) + ['contract_drift_or_unverified'])),
                  'research_run_id': s.get('research_run_id')} for s in (slots or manifest['slots'])]
    state = 'failed' if any(s['status'] == 'failed' for s in slots) else 'passed' if all(s['status'] == 'passed' for s in slots) else 'in_progress'
    return {k: row[k] for k in ('cohort_id', 'manifest_sha256', 'registered_at', 'actor')} | {
        'status': state, 'slots': slots, 'evaluation': 'campaign-v2'}
