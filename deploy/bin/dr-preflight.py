#!/usr/bin/env python3
"""Read-only DR inventory; never treats same-host checks as host reconstruction."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

STAMP = re.compile(r'20\d{6}T\d{6}Z')
TIMERS = ('tick', 'watchdog', 'private-state', 'research', 'collector',
          'analytics', 'backup', 'postgres-sync', 'offsite-backup')


def run(args, timeout=30):
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if p.returncode:
        raise ValueError('command_failed')  # stderr may contain credentials
    return p.stdout.strip()


def timestamp(value):
    d = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if d.tzinfo is None:
        raise ValueError('timezone_required')
    return d


def latest(base):
    choices = sorted(p for p in base.iterdir() if STAMP.fullmatch(p.name)
                     and p.is_dir() and not p.is_symlink())
    if not choices:
        raise ValueError('backup_missing')
    directory = choices[-1]
    manifest = directory / 'manifest.json'
    if manifest.is_symlink() or manifest.stat().st_size > 10485760:
        raise ValueError('unsafe_manifest')
    return directory, json.loads(manifest.read_text())


def age(stamp, now):
    # Source snapshot start, not upload/seal completion, defines data age.
    return int((now - datetime.strptime(stamp, '%Y%m%dT%H%M%SZ')
                .replace(tzinfo=timezone.utc)).total_seconds())


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo', type=Path, default=Path('/opt/orbital/services/mova-fpl'))
    ap.add_argument('--backup-root', type=Path, default=Path('/opt/orbital/backups/mova-fpl'))
    ap.add_argument('--snapshots', type=Path, required=True)
    ap.add_argument('--expected-revision', required=True)
    ap.add_argument('--mode', choices=('source', 'recovered-host'), default='source')
    ap.add_argument('--source-host-fingerprint')
    args = ap.parse_args()
    if not re.fullmatch(r'[0-9a-f]{7,40}', args.expected_revision):
        ap.error('expected revision must be a Git SHA')
    now = datetime.now(timezone.utc)
    checks = []
    facts = {}

    def check(name, fn):
        try:
            detail = fn()
            checks.append({'name': name, 'status': 'pass', 'detail': detail})
        except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError):
            checks.append({'name': name, 'status': 'blocked'})

    def backups():
        sq, sm = latest(args.backup_root)
        pg, pm = latest(args.backup_root / 'postgres')
        if (sm['schema'] != 'mova-fpl-backup-v2'
                or pm['schema'] != 'mova-postgres-backup-v2'
                or {f['name'] for f in sm['files']} != {'ops.db', 'trace.db', 'fpl_canonical.db'}
                or len(sm['files']) != 3 or len(sm['models']) != 2
                or {m['family'] for m in sm['models']} != {'minutes', 'points'}
                or not pm['inventory']['tables']):
            raise ValueError('contract')
        ages = [age(sq.name, now), age(pg.name, now)]
        facts['local_backup'] = {'sqlite': sq.name, 'postgres': pg.name,
                                 'data_age_seconds': max(ages),
                                 'postgres_tables': len(pm['inventory']['tables'])}
        if min(ages) < 0 or max(ages) > 7 * 3600:
            raise ValueError('local_rpo')
        return facts['local_backup']

    def remote():
        rows = json.loads(args.snapshots.read_text())
        candidates = []
        root = str(args.backup_root).rstrip('/')
        for r in rows:
            paths = r.get('paths', [])
            if 'mova-fpl' not in r.get('tags', []) or len(paths) != 2:
                continue
            sq = [p[len(root)+1:] for p in paths if p.startswith(root + '/')
                  and STAMP.fullmatch(p[len(root)+1:])]
            pg = [p[len(root)+10:] for p in paths if p.startswith(root + '/postgres/')
                  and STAMP.fullmatch(p[len(root)+10:])]
            if len(sq) == len(pg) == 1 and re.fullmatch(r'[0-9a-f]{64}', r.get('id', '')):
                uploaded = timestamp(r['time'])
                if uploaded > now:
                    raise ValueError('future_snapshot')
                candidates.append((uploaded, r['id'], sq[0], pg[0]))
        if not candidates:
            raise ValueError('remote_missing')
        uploaded, sid, sq, pg = max(candidates)
        data_age = max(age(sq, now), age(pg, now))
        facts['remote_backup'] = {'snapshot_id_prefix': sid[:12],
                                  'uploaded_at': uploaded.isoformat(),
                                  'sqlite': sq, 'postgres': pg,
                                  'data_age_seconds': data_age}
        if min(age(sq, now), age(pg, now)) < 0 or data_age > 7 * 3600:
            raise ValueError('remote_rpo')
        return facts['remote_backup']

    def revision():
        sha = run(['git', '-C', str(args.repo), 'rev-parse', 'HEAD'])
        if not sha.startswith(args.expected_revision):
            raise ValueError('checkout_revision')
        for c in ('api', 'browser'):
            tag = run(['docker', 'inspect', 'mova-fpl-' + c + '-1', '--format',
                       '{{ index .Config.Labels "org.opencontainers.image.revision" }}'])
            if not sha.startswith(tag) or len(tag) < 7:
                raise ValueError('image_revision')
        return {'checkout': sha}

    def timers():
        for t in TIMERS:
            if run(['systemctl', 'is-active', 'mova-fpl-' + t + '.timer']) != 'active':
                raise ValueError('timer')
        return {'active': len(TIMERS)}

    def resources():
        free = shutil.disk_usage(args.repo).free
        if free < 5 * 1024**3:
            raise ValueError('disk_capacity')
        return {'disk_free_bytes': free, 'isolated_restore_minimum_bytes': 5 * 1024**3}

    machine = hashlib.sha256(Path('/etc/machine-id').read_bytes().strip()).hexdigest()
    check('local_v2_within_rpo', backups)
    check('external_snapshot_within_rpo', remote)
    check('checkout_images_match', revision)
    check('timers', timers)
    check('restore_resources', resources)
    check('api_ready', lambda: json.loads(run(['curl', '-fsS', '--max-time', '10',
                                              'http://127.0.0.1:8787/readyz'])))
    if args.mode == 'recovered-host':
        def distinct():
            if (not re.fullmatch(r'[0-9a-f]{64}', args.source_host_fingerprint or '')
                    or machine == args.source_host_fingerprint):
                raise ValueError('same_or_unknown_host')
            return {'distinct_host': True}
        check('distinct_recovery_host', distinct)
        def doctor():
            d = json.loads(run(['/usr/local/bin/mova', 'doctor', '--json'], 240).splitlines()[-1])
            if d['summary']['fail'] or d['summary']['warn'] or not d['observability']['available']:
                raise ValueError('doctor')
            return d['summary']
        check('recovered_runtime_doctor', doctor)
    blocked = sum(c['status'] == 'blocked' for c in checks)
    print(json.dumps({'schema': 'mova-dr-preflight-v1', 'generated_at': now.isoformat(),
                      'mode': args.mode, 'host_fingerprint': machine,
                      'status': 'blocked' if blocked else 'technical_checks_pass',
                      'checks': checks, 'facts': facts,
                      'targets': {'backup_interval_hours': 6, 'rpo_hours': 7,
                                  'data_model_restore_rto_minutes': 15,
                                  'host_rebuild_rto_minutes': 120},
                      'host_reconstruction_proven': False,
                      'acceptance_pending': ['new_host_full_restore',
                                             'external_audit_artifacts',
                                             'supervised_browser_codex_auth',
                                             'provider_reads_and_rto_measurement'],
                      'runtime_mutated': False}, sort_keys=True))
    return 2 if blocked else 0


if __name__ == '__main__':
    raise SystemExit(main())
