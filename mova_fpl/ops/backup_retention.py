"""Bounded local backup retention; root host facade, no database access or secrets."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

STAMP = re.compile(r"20\d{6}T\d{6}Z")
GIB = 1024 ** 3
POLICY = {"version": "local-backups-v1", "recent_hours": 48,
          "recent_bucket_hours": 6, "daily_days": 7, "weekly_days": 28,
          "protected_latest": 2, "family_budget_bytes": 6 * GIB}


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inventory(directory: Path, family: str) -> dict:
    """Only complete, allowlisted backup directories can enter deletion plans."""
    if directory.is_symlink() or directory.resolve()!=directory.absolute() or not directory.is_dir() or not STAMP.fullmatch(directory.name):
        raise ValueError('not a canonical backup directory')
    manifest_path = directory / 'manifest.json'
    if manifest_path.is_symlink() or manifest_path.stat().st_size > 4 * 1024 ** 2:
        raise ValueError('unsafe manifest')
    manifest = json.loads(manifest_path.read_text())
    if family == 'sqlite':
        if manifest.get('schema') not in {'mova-fpl-backup-v1', 'mova-fpl-backup-v2'}:
            raise ValueError('unknown SQLite backup schema')
        entries = list(manifest.get('files') or []) + list(manifest.get('models') or [])
        if {r['name'] for r in manifest.get('files', [])} != {'ops.db', 'trace.db', 'fpl_canonical.db'}:
            raise ValueError('incomplete SQLite set')
    else:
        if manifest.get('schema') != 'mova-postgres-backup-v2' or not (manifest.get('inventory') or {}).get('tables'):
            raise ValueError('content-sealed PostgreSQL backup required')
        entries = [manifest['dump']]
        if entries[0]['name'] != 'postgres-shadow.dump':
            raise ValueError('unexpected dump file')
    expected = {'manifest.json'}
    total = manifest_path.stat().st_size
    for item in entries:
        name = str(item['name'])
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts or name in expected:
            raise ValueError('unsafe backup member')
        member = directory / relative
        if member.is_symlink() or not member.is_file() or not member.resolve().is_relative_to(directory.resolve()):
            raise ValueError('unsafe backup member')
        size = int(item.get('size', item.get('bytes', -1)))
        if member.stat().st_size != size or not re.fullmatch('[0-9a-f]{64}', str(item.get('sha256', ''))):
            raise ValueError('invalid backup inventory')
        expected.add(name)
        total += size
    for member in directory.rglob('*'):
        if member.is_symlink():
            raise ValueError('unlisted or symlinked member')
        if member.is_file() and str(member.relative_to(directory)) not in expected:
            # Empty WALs and rebuildable SHM indexes are emitted by SQLite's
            # sealed-backup resolver; a nonempty WAL is never assumed disposable.
            extra=str(member.relative_to(directory))
            empty_wal=family=='sqlite' and extra in {n+'-wal' for n in ('ops.db','trace.db','fpl_canonical.db')} and member.stat().st_size==0
            shm=family=='sqlite' and extra in {n+'-shm' for n in ('ops.db','trace.db','fpl_canonical.db')} and member.stat().st_size<=32768
            if not (empty_wal or shm):
                raise ValueError('unlisted or symlinked member')
            total+=member.stat().st_size
    return {'path': str(directory), 'family': family, 'name': directory.name,
            'timestamp': datetime.strptime(directory.name, '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc).timestamp(),
            'bytes': total, 'manifest_sha256': digest(manifest_path)}


def verify(row: dict) -> None:
    directory = Path(row['path'])
    if inventory(directory, row['family']) != row:
        raise ValueError('backup changed after planning')
    manifest = json.loads((directory / 'manifest.json').read_text())
    entries = list(manifest.get('files', [])) + list(manifest.get('models', [])) if row['family'] == 'sqlite' else [manifest['dump']]
    for item in entries:
        if digest(directory / item['name']) != item['sha256']:
            raise ValueError('backup content hash mismatch')


def plan(root: Path, *, now: datetime | None = None, policy: dict | None = None) -> dict:
    rules = {**POLICY, **(policy or {})}
    current = now or datetime.now(timezone.utc)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('unsafe backup root')
    keep, candidates, skipped = [], [], []
    for family, parent in [('sqlite', root), ('postgres', root / 'postgres')]:
        if parent.is_symlink():
            raise ValueError('unsafe family root')
        rows = []
        for directory in sorted(parent.iterdir()) if parent.is_dir() else []:
            if not STAMP.fullmatch(directory.name):
                continue
            try:
                row = inventory(directory, family)
                if row['timestamp'] > current.timestamp():
                    raise ValueError('future backup')
                rows.append(row)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                skipped.append({'path': str(directory), 'reason': str(exc)[:160]})
        rows.sort(key=lambda row: row['timestamp'], reverse=True)
        # Two verified recent sets per existing family are mandatory before deletion.
        if rows and len(rows) < rules['protected_latest']:
            keep.extend(rows)
            continue
        selected = {row['name'] for row in rows[:rules['protected_latest']]}
        for days, width in [(rules['recent_hours']/24, rules['recent_bucket_hours']*3600),
                            (rules['daily_days'],86400), (rules['weekly_days'],7*86400)]:
            buckets = set()
            for row in rows:
                age = current.timestamp() - row['timestamp']
                if age <= days*86400:
                    bucket = int(row['timestamp']//width)
                    if bucket not in buckets:
                        selected.add(row['name']); buckets.add(bucket)
        protected = {r['name'] for r in rows[:rules['protected_latest']]}
        retained = [r for r in rows if r['name'] in selected]
        while sum(r['bytes'] for r in retained) > rules['family_budget_bytes']:
            expendable = [r for r in reversed(retained) if r['name'] not in protected]
            if not expendable:
                raise ValueError('protected backups exceed local budget; operator action required')
            retained.remove(expendable[0])
        selected = {r['name'] for r in retained}
        keep.extend(retained)
        candidates.extend(r for r in rows if r['name'] not in selected)
    return {'schema':'mova-backup-retention-v1','policy':rules,'root':str(root),
            'planned_at':current.isoformat(),'keep':keep,'candidates':candidates,'skipped':skipped,
            'candidate_bytes':sum(r['bytes'] for r in candidates),
            'retained_bytes':sum(r['bytes'] for r in keep)}


def run(root: Path, receipt_root: Path, *, apply: bool = False, actor: str = '',
        reason: str = '', idempotency_key: str = '', now: datetime | None = None,
        policy: dict | None = None) -> dict:
    if not apply:
        return {**plan(root, now=now, policy=policy), 'mode':'dry-run'}
    if not all(value.strip() for value in (actor,reason,idempotency_key)):
        raise ValueError('apply requires actor, reason and idempotency key')
    identity = {'actor':actor,'reason':reason,'idempotency_key':idempotency_key,
                'root':str(root),'policy':{**POLICY,**(policy or {})}}
    receipt_root.mkdir(parents=True,exist_ok=True,mode=0o700)
    info=receipt_root.lstat()
    if receipt_root.is_symlink() or info.st_uid!=os.getuid() or info.st_mode & 0o022:
        raise ValueError('unsafe retention receipt root')
    target = receipt_root / (hashlib.sha256(idempotency_key.encode()).hexdigest()+'.json')
    if target.is_symlink():
        raise ValueError('unsafe retention receipt')
    is_new=not target.exists()
    if not is_new:
        receipt=json.loads(target.read_text())
        if receipt['identity'] != identity:
            raise ValueError('retention idempotency conflict')
        if receipt['status']=='completed':
            return {**receipt,'reused':True}
    else:
        proposal=plan(root,now=now,policy=policy)
        receipt={'identity':identity,'plan':proposal,'status':'applying','removed':[],'removed_bytes':0}
    for family in ('sqlite','postgres'):
        if any(r['family']==family for r in receipt['plan']['candidates']):
            recent=sorted([r for r in receipt['plan']['keep'] if r['family']==family],key=lambda r:r['timestamp'],reverse=True)[:2]
            if len(recent)!=2:
                raise ValueError('two protected backups required')
            if (now or datetime.now(timezone.utc)).timestamp()-recent[0]['timestamp']>7*3600:
                raise ValueError('fresh protected backup required before pruning')
            for row in recent:
                parent=root if family=='sqlite' else root/'postgres'
                if Path(row['path']).parent!=parent or not STAMP.fullmatch(Path(row['path']).name):
                    raise ValueError('protected set escaped backup root')
                verify(row)
    if is_new:
        with target.open('x') as stream:
            json.dump(receipt,stream,sort_keys=True);stream.flush();os.fsync(stream.fileno())
    def save():
        temporary=target.with_suffix('.tmp')
        temporary.write_text(json.dumps(receipt,sort_keys=True)+'\n');temporary.replace(target)
    for row in receipt['plan']['candidates']:
        if row['path'] in receipt['removed']: continue
        directory=Path(row['path'])
        parent=root if row['family']=='sqlite' else root/'postgres'
        if directory.parent != parent or not STAMP.fullmatch(directory.name):
            raise ValueError('candidate escaped backup root')
        if directory.exists():
            if inventory(directory,row['family']) != row:
                raise ValueError('deletion candidate changed; retain and inspect')
            flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW
            root_fd=os.open(root,flags)
            try:
                parent_fd=os.open('postgres',flags,dir_fd=root_fd) if row['family']=='postgres' else os.dup(root_fd)
                try:
                    shutil.rmtree(directory.name,dir_fd=parent_fd)
                finally:
                    os.close(parent_fd)
            finally:
                os.close(root_fd)
        receipt['removed'].append(row['path']);receipt['removed_bytes']+=row['bytes'];save()
    receipt['status']='completed';receipt['finished_at']=datetime.now(timezone.utc).isoformat();save()
    return receipt


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--receipt-root',type=Path,required=True)
    parser.add_argument('--apply',action='store_true')
    for name in ('actor','reason','idempotency-key'):parser.add_argument('--'+name,default='')
    args=parser.parse_args()
    result=run(args.root,args.receipt_root,apply=args.apply,actor=args.actor,
               reason=args.reason,idempotency_key=args.idempotency_key)
    if args.apply:
        result={'schema':'mova-backup-retention-v1','status':result['status'],
                'reused':result.get('reused',False),'removed_count':len(result['removed']),
                'removed_bytes':result['removed_bytes'],'retained_bytes':result['plan']['retained_bytes'],
                'skipped_count':len(result['plan']['skipped']),
                'receipt_path':str(args.receipt_root/(hashlib.sha256(args.idempotency_key.encode()).hexdigest()+'.json'))}
    print(json.dumps(result,sort_keys=True))


if __name__=='__main__':main()
