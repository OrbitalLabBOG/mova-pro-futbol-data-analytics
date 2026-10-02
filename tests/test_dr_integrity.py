"""Regression coverage for incomplete, corrupt and obsolete recovery evidence."""
import hashlib
import json
import sqlite3
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from mova_fpl.ops.postgres_backup import content_sql, verify_inventory
from mova_fpl.ops.readiness import dr_evidence_validity
from mova_fpl.ops.sqlite_restore import verify


def sealed_sqlite(root):
    files = []
    for name in ('ops.db', 'trace.db', 'fpl_canonical.db'):
        path = root / name
        with sqlite3.connect(path) as con:
            con.execute('CREATE TABLE fixture (id INTEGER PRIMARY KEY, value TEXT)')
            con.execute("INSERT INTO fixture VALUES (1, 'recoverable')")
        files.append({'name': name, 'size': path.stat().st_size,
                      'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    import joblib
    models = []
    for family in ('minutes', 'points'):
        name = f'models/{family}/{family}-1.1.0.joblib'
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({'family': family}, path)
        models.append({'name': name, 'family': family, 'version': '1.1.0',
                       'size': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    manifest = {'schema': 'mova-fpl-backup-v2', 'files': files, 'models': models}
    (root / 'manifest.json').write_text(json.dumps(manifest))
    return manifest


def test_sqlite_restore_reads_all_databases_without_mutation(tmp_path):
    sealed_sqlite(tmp_path)
    before = {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    result = verify(tmp_path)
    assert {x['name'] for x in result['databases']} == {'ops.db', 'trace.db', 'fpl_canonical.db'}
    assert result['runtime_mutated'] is False
    assert before == {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}


@pytest.mark.parametrize('name', ['trace.db', 'fpl_canonical.db'])
def test_sqlite_restore_rejects_checksum_correct_but_corrupt_optional_db(tmp_path, name):
    manifest = sealed_sqlite(tmp_path)
    path = tmp_path / name
    path.write_bytes(b'not a sqlite database')
    row = next(x for x in manifest['files'] if x['name'] == name)
    row.update(size=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(sqlite3.DatabaseError):
        verify(tmp_path)


def test_sqlite_restore_rejects_incomplete_manifest(tmp_path):
    manifest = sealed_sqlite(tmp_path)
    manifest['files'].pop()
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='complete'):
        verify(tmp_path)


@pytest.mark.parametrize('change', ['content', 'rows', 'columns', 'missing', 'extra'])
def test_postgres_restore_rejects_semantic_data_or_schema_drift(change):
    expected = {'schema': 'mova-postgres-content-v1', 'tables': [
        {'schema': 'ops', 'name': 'events', 'rows': 3, 'content_sha256': 'a' * 64,
         'columns': [{'name': 'id', 'type': 'pg_catalog.int4'}]}]}
    observed = deepcopy(expected)
    if change == 'content':
        observed['tables'][0]['content_sha256'] = 'b' * 64
    elif change == 'rows':
        observed['tables'][0]['rows'] = 2
    elif change == 'columns':
        observed['tables'][0]['columns'][0]['type'] = 'pg_catalog.text'
    elif change == 'missing':
        observed['tables'] = []
    else:
        observed['tables'].append({**observed['tables'][0], 'name': 'extra'})
    with pytest.raises(ValueError, match='differ'):
        verify_inventory(expected, observed)


def test_content_inventory_quotes_unusual_identifiers_and_sorts_row_hashes():
    sql = content_sql([{'schema': "op's", 'name': 'a"b'}])
    assert '"op\'s"."a""b"' in sql
    assert "'op''s'" in sql
    assert 'ORDER BY row_hash' in sql


def test_dr_gate_requires_matching_revision_recent_timezone_and_no_future():
    now = datetime(2026, 10, 2, tzinfo=timezone.utc)
    row = {'revision': 'abc1234', 'finished_at': now.isoformat()}
    assert dr_evidence_validity(row, 'abc1234', now)['valid'] is True
    for bad in ({**row, 'revision': 'old1234'}, {**row, 'revision': None},
                {**row, 'finished_at': (now - timedelta(days=31)).isoformat()},
                {**row, 'finished_at': (now + timedelta(seconds=1)).isoformat()},
                {**row, 'finished_at': '2026-10-02'}, {**row, 'finished_at': None}):
        assert dr_evidence_validity(bad, 'abc1234', now)['valid'] is False


def test_readiness_does_not_turn_historical_success_into_current_dr_pass():
    from mova_fpl.ops.readiness import evaluate_readiness
    now = '2026-10-02T12:00:00+00:00'
    scenarios = {name: {'status': 'completed', 'checks': checks, 'passed': checks,
                       'revision': 'abc1234', 'finished_at': now}
                 for name, checks in (('api_recovery', 5), ('postgres_recovery', 8),
                                      ('browser_recovery', 9), ('combined_recovery', 13),
                                      ('reboot_recovery', 11))}
    kwargs = dict(operator_status={'runtime': {'git_sha': 'abc1234'}},
                  research_coverage={}, execution_status={}, generated_at=now,
                  host_recovery_evidence={'status': 'completed', 'completed': 5,
                                          'required': 5, 'scenarios': scenarios},
                  offsite_restore_evidence={'status': 'completed', 'checks': 8,
                                             'passed': 8, 'revision': 'abc1234',
                                             'finished_at': now})
    gates = {x['code']: x for x in evaluate_readiness(**kwargs)['gates']}
    assert gates['HOST_RECOVERY_DRILLS_PROVEN']['status'] == 'pass'
    assert gates['OFF_HOST_RESTORE_PROVEN']['status'] == 'pass'
    kwargs['host_recovery_evidence']['scenarios']['reboot_recovery']['revision'] = 'old1234'
    kwargs['offsite_restore_evidence']['finished_at'] = '2026-08-30T12:00:00+00:00'
    gates = {x['code']: x for x in evaluate_readiness(**kwargs)['gates']}
    assert gates['HOST_RECOVERY_DRILLS_PROVEN']['status'] == 'pending'
    assert gates['OFF_HOST_RESTORE_PROVEN']['status'] == 'pending'
    assert gates['OFF_HOST_RESTORE_PROVEN']['observed']['validity']['reasons']


def test_backup_rejects_missing_active_model_without_publishing(tmp_path):
    from mova_fpl.ops.config import RuntimeConfig
    from mova_fpl.ops.backup import create_backup
    from mova_fpl.ops.db import OpsDB
    cfg = RuntimeConfig(ops_db=tmp_path/'ops.db', trace_db=tmp_path/'trace.db',
                        canonical_db=tmp_path/'fpl_canonical.db',
                        artifact_root=tmp_path/'artifacts', backup_root=tmp_path/'backups')
    db = OpsDB(cfg.ops_db, enforce_version=False)
    db.migrate()
    for p in (cfg.trace_db, cfg.canonical_db):
        with sqlite3.connect(p) as con:
            con.execute('CREATE TABLE fixture(id integer)')
    with pytest.raises(ValueError, match='baseline'):
        create_backup(cfg, db)
    assert list(cfg.backup_root.iterdir()) == []


def test_importing_old_dr_evidence_does_not_refresh_its_actual_age():
    now = datetime(2026, 10, 2, tzinfo=timezone.utc)
    row = {'revision': 'abc1234', 'finished_at': now.isoformat(),
           'evidence_finished_at': '2026-08-30T12:00:00+00:00'}
    validity = dr_evidence_validity(row, 'abc1234', now)
    assert validity['valid'] is False
    assert 'evidence_expired_or_future' in validity['reasons']


@pytest.mark.parametrize('backup_exit', [0, 31])
def test_postgres_backup_restores_temporary_cpu_budget(tmp_path, monkeypatch, backup_exit):
    import os
    import shlex
    import subprocess
    import sys
    from pathlib import Path

    scripts = tmp_path / 'bin'
    scripts.mkdir()
    docker = scripts / 'docker'
    docker.write_text('''#!/bin/bash
if [[ "$1 $2 $3 $4" == "compose ps -q postgres" ]]; then echo fixture; exit 0; fi
if [[ "$1" == inspect ]]; then echo 100000000; exit 0; fi
if [[ "$1" == update ]]; then echo "$*" >> "$CPU_LOG"; exit 0; fi
exit 0
''')
    python = scripts / 'python3'
    python.write_text('''#!/bin/bash
if [[ "$1" == -m ]]; then
  touch "$4/postgres-shadow.dump"
  echo '{}' > "$4/manifest.json"
  exit "$BACKUP_EXIT"
fi
exec ''' + shlex.quote(sys.executable) + ''' "$@"
''')
    git = scripts / 'git'
    git.write_text('#!/bin/bash\necho fixture123\n')
    for path in (docker, python, git):
        path.chmod(0o755)
    log = tmp_path / 'cpu.log'
    monkeypatch.setenv('PATH', str(scripts) + os.pathsep + os.environ['PATH'])
    monkeypatch.setenv('MOVA_REPO_DIR', str(tmp_path))
    monkeypatch.setenv('MOVA_DEPLOY_ENV', str(tmp_path / 'absent.env'))
    monkeypatch.setenv('MOVA_BACKUP_ROOT', str(tmp_path / 'backups'))
    monkeypatch.setenv('CPU_LOG', str(log))
    monkeypatch.setenv('BACKUP_EXIT', str(backup_exit))
    monkeypatch.delenv('MOVA_POSTGRES_BACKUP_CPUS', raising=False)
    script = Path(__file__).resolve().parents[1] / 'deploy/bin/postgres-shadow-backup.sh'
    result = subprocess.run(['bash', str(script)], capture_output=True, text=True)
    assert result.returncode == backup_exit, result.stderr
    assert log.read_text().splitlines() == [
        'update --cpus 0.50 fixture', 'update --cpus 0.100000000 fixture']
    assert not list((tmp_path / 'backups/postgres').glob('.*.partial'))
