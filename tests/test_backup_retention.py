from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mova_fpl.ops.backup_retention import POLICY, plan, run

NOW=datetime(2026,10,19,16,0,tzinfo=timezone.utc)


def backup(root,at,family='sqlite',payload=b'fixture'):
    directory=(root if family=='sqlite' else root/'postgres')/at.strftime('%Y%m%dT%H%M%SZ')
    directory.mkdir(parents=True,exist_ok=True)
    def item(name):
        (directory/name).write_bytes(payload)
        return {'name':name,'size':len(payload),'sha256':hashlib.sha256(payload).hexdigest()}
    if family=='sqlite':
        manifest={'schema':'mova-fpl-backup-v2','files':[item(n) for n in ('ops.db','trace.db','fpl_canonical.db')],'models':[]}
    else:
        row=item('postgres-shadow.dump');row['bytes']=row.pop('size')
        manifest={'schema':'mova-postgres-backup-v2','dump':row,'inventory':{'tables':[{'schema':'ops','name':'jobs'}]}}
    (directory/'manifest.json').write_text(json.dumps(manifest))
    return directory


def series(root):
    for family in ('sqlite','postgres'):
        for hours in range(0,36*24,3):backup(root,NOW-timedelta(hours=hours),family)


def test_dense_backups_are_tiered_and_dry_run_preserves_everything(tmp_path):
    root=tmp_path/'backups';series(root)
    sentinel=root/'release-rollback';sentinel.mkdir();(sentinel/'untouched').touch()
    proposal=plan(root,now=NOW)
    assert len(proposal['keep'])<50
    assert len(proposal['candidates'])>500
    assert all(Path(r['path']).exists() for r in proposal['candidates'])
    for family in ('sqlite','postgres'):
        kept=[r for r in proposal['keep'] if r['family']==family]
        assert all((NOW-timedelta(hours=h)).strftime('%Y%m%dT%H%M%SZ') in {r['name'] for r in kept} for h in (0,3))
        assert any(NOW.timestamp()-r['timestamp']>14*86400 for r in kept)
    assert (sentinel/'untouched').exists()


def test_apply_verifies_recent_sets_records_and_replays_without_new_deletion(tmp_path):
    root=tmp_path/'backups';series(root)
    receipts=tmp_path/'receipts'
    kwargs=dict(apply=True,actor='julian',reason='bounded recovery',idempotency_key='test-1',now=NOW)
    result=run(root,receipts,**kwargs)
    assert result['status']=='completed' and result['removed_bytes']>0
    assert all(Path(r['path']).exists() for r in result['plan']['keep'])
    assert not any(Path(r).exists() for r in result['removed'])
    new=backup(root,NOW+timedelta(seconds=1))
    assert run(root,receipts,**kwargs)['reused'] is True and new.exists()
    with pytest.raises(ValueError,match='conflict'):run(root,receipts,**{**kwargs,'reason':'different'})


def test_hash_tamper_and_stale_latest_block_before_any_removal(tmp_path):
    root=tmp_path/'backups';series(root)
    newest=root/NOW.strftime('%Y%m%dT%H%M%SZ')/'ops.db';newest.write_bytes(b'tamper!')
    with pytest.raises(ValueError):run(root,tmp_path/'r',apply=True,actor='j',reason='r',idempotency_key='k',now=NOW)
    assert len(list(root.glob('20*')))>200
    newest.write_bytes(b'fixture')
    with pytest.raises(ValueError,match='fresh'):run(root,tmp_path/'r',apply=True,actor='j',reason='r',idempotency_key='k',now=NOW+timedelta(days=2))


def test_symlinks_unknown_content_and_future_directories_are_never_deleted(tmp_path):
    root=tmp_path/'backups';series(root)
    outside=tmp_path/'outside';outside.mkdir();(outside/'secret').write_text('preserve')
    link=root/'20260101T000000Z';link.symlink_to(outside,target_is_directory=True)
    extra=backup(root,NOW-timedelta(days=32));(extra/'unknown').touch()
    future=backup(root,NOW+timedelta(days=1))
    result=run(root,tmp_path/'r',apply=True,actor='j',reason='r',idempotency_key='k',now=NOW)
    assert link.is_symlink() and (outside/'secret').exists() and extra.exists() and future.exists()
    assert len(result['plan']['skipped'])>=3


def test_byte_budget_is_enforced_but_never_removes_two_protected_sets(tmp_path):
    root=tmp_path/'backups';series(root)
    minimum=sum(r['bytes'] for r in plan(root,now=NOW)['keep'][:2])
    result=plan(root,now=NOW,policy={'family_budget_bytes':minimum+10})
    for family in ('sqlite','postgres'):
        rows=[r for r in result['keep'] if r['family']==family]
        assert len(rows)>=2 and sum(r['bytes'] for r in rows)<=minimum+10
    with pytest.raises(ValueError,match='budget'):plan(root,now=NOW,policy={'family_budget_bytes':1})


def test_unverified_single_backup_and_actorless_apply_never_prune(tmp_path):
    root=tmp_path/'b';backup(root,NOW-timedelta(days=50))
    assert plan(root,now=NOW)['candidates']==[]
    with pytest.raises(ValueError,match='actor'):run(root,tmp_path/'r',apply=True)


def test_empty_wal_and_rebuildable_shm_are_known_but_nonempty_wal_blocks(tmp_path):
    root=tmp_path/'b';series(root)
    directory=root/NOW.strftime('%Y%m%dT%H%M%SZ')
    (directory/'ops.db-wal').touch();(directory/'ops.db-shm').write_bytes(b'x'*32768)
    assert not plan(root,now=NOW)['skipped']
    (directory/'ops.db-wal').write_bytes(b'uncheckpointed')
    proposal=plan(root,now=NOW)
    assert str(directory) in {r['path'] for r in proposal['skipped']}
    assert str(directory) not in {r['path'] for r in proposal['candidates']}


def test_interrupted_prune_resumes_original_plan_and_rechecks_protected_hashes(tmp_path,monkeypatch):
    import shutil
    root=tmp_path/'b';series(root);receipts=tmp_path/'r'
    original=shutil.rmtree;calls=[]
    def interrupted(path,**kwargs):
        calls.append(str(path))
        if len(calls)==2:raise OSError('interrupted')
        return original(path,**kwargs)
    kwargs=dict(apply=True,actor='j',reason='recovery',idempotency_key='k',now=NOW)
    monkeypatch.setattr('mova_fpl.ops.backup_retention.shutil.rmtree',interrupted)
    with pytest.raises(OSError,match='interrupted'):run(root,receipts,**kwargs)
    newest=root/NOW.strftime('%Y%m%dT%H%M%SZ')/'ops.db';newest.write_bytes(b'tamper!')
    with pytest.raises(ValueError,match='hash'):run(root,receipts,**kwargs)
    newest.write_bytes(b'fixture')
    monkeypatch.setattr('mova_fpl.ops.backup_retention.shutil.rmtree',original)
    finished=run(root,receipts,**kwargs)
    assert finished['status']=='completed' and len(set(finished['removed']))==len(finished['removed'])
    assert Path(finished['removed'][0]).name==calls[0]


def test_family_symlink_cannot_escape_even_when_resuming(tmp_path,monkeypatch):
    import shutil
    root=tmp_path/'b';series(root);receipts=tmp_path/'r'
    original=shutil.rmtree
    monkeypatch.setattr('mova_fpl.ops.backup_retention.shutil.rmtree',lambda *a,**k:(_ for _ in ()).throw(OSError('stop')))
    kwargs=dict(apply=True,actor='j',reason='r',idempotency_key='k',now=NOW)
    with pytest.raises(OSError):run(root,receipts,**kwargs)
    outside=tmp_path/'outside';(root/'postgres').rename(outside)
    (root/'postgres').symlink_to(outside,target_is_directory=True)
    monkeypatch.setattr('mova_fpl.ops.backup_retention.shutil.rmtree',original)
    before=len(list(outside.iterdir()))
    with pytest.raises(ValueError):run(root,receipts,**kwargs)
    assert len(list(outside.iterdir()))==before
