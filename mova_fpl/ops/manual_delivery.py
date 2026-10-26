"""A verified owner override holds its own cycle, never the permanent authority."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from mova_fpl.ops.db import sha256_json


def hold(db, cycle_id):
    if not cycle_id:
        return None
    with db.connect(readonly=True) as con:
        row = con.execute(
            """SELECT e.*,d.cycle_id,d.fingerprint,d.artifact_path,
            d.manifest_sha256,a.payload_json,a.payload_sha256
            FROM web_executions e JOIN decision_runs d ON d.decision_id=e.decision_id
            JOIN audit_events a ON a.subject_id=e.execution_id
              AND a.subject_type='web_execution'
              AND a.event_type='manual_verified_execution_recorded'
            WHERE d.cycle_id=? AND e.status='verified'
            ORDER BY e.finished_at DESC,e.rowid DESC LIMIT 1""", (cycle_id,),
        ).fetchone()
    return dict(row) if row else None


def receipt(config, db, cycle_id):
    """Read-only manual evidence, distinct from a scheduler final receipt.

    A damaged receipt still leaves the hold in force; it cannot enable another Save.
    """
    row = hold(db, cycle_id)
    if not row:
        return None
    latest = db.latest_delivery_attempt(cycle_id)
    if latest and latest['status'] in {'claimed', 'applying', 'ambiguous'}:
        return None
    try:
        audit = json.loads(row['payload_json'])
        if sha256_json(audit) != row['payload_sha256']:
            return None
        for path_key, hash_key in [('evidence_path', 'evidence_sha256'),
                                    ('artifact_path', 'manifest_sha256')]:
            path = Path(row[path_key])
            if (not path.resolve().is_relative_to(config.artifact_root.resolve())
                    or not path.is_file()
                    or hashlib.sha256(path.read_bytes()).hexdigest() != row[hash_key]):
                return None
        with db.connect(readonly=True) as con:
            checks = con.execute('SELECT check_name,passed FROM verification_checks WHERE execution_id=?',
                                 (row['execution_id'],)).fetchall()
            players = con.execute('SELECT squad_position FROM decision_players WHERE decision_id=?',
                                  (row['decision_id'],)).fetchall()
        required = {'authorization', 'pre_state', 'post_reload_state', 'exact_diff'}
        if (not required <= {c['check_name'] for c in checks if c['passed']}
                or any(not c['passed'] for c in checks)
                or sorted(p['squad_position'] for p in players) != list(range(1, 16))
                or audit.get('decision_id') != row['decision_id']
                or audit.get('post_fingerprint') != row['fingerprint']):
            return None
    except (OSError, ValueError, TypeError, KeyError):
        return None
    return {'status': 'manual_verified', 'cycle_id': cycle_id,
            'execution_id': row['execution_id'], 'decision_id': row['decision_id'],
            'finished_at': row['finished_at'], 'evidence_sha256': row['evidence_sha256'],
            'scheduler_save': False}
