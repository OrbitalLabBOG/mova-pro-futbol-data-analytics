"""Resolve clock-conflicted snapshots with later ancestor or identical-blob pushes."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
from experiments.data_ground_truth.geek_publication import public_push
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked


def git(repo,*args):
    return subprocess.check_output(['git','--no-replace-objects','-C',str(repo),*args])


def proof(repo,commit,data,event):
    if not public_push(event):return None
    head=event['payload']['head']
    blob=git(repo,'rev-parse',commit+':app/js/data.json').decode().strip()
    expected=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
    if blob!=expected or git(repo,'cat-file','blob',blob)!=data:
        raise ValueError('snapshot differs from committed Git blob')
    ancestor=subprocess.run(['git','--no-replace-objects','-C',str(repo),'merge-base','--is-ancestor',commit,head],capture_output=True)
    if ancestor.returncode==0:
        return dict(evidence_kind='ancestor_public_push',source_blob_sha1=blob,published_head=head,published_path=None)
    if ancestor.returncode!=1:
        raise ValueError('cannot inspect Git ancestry')
    for line in git(repo,'ls-tree','-r','--full-tree',head,'--','app/js/data.json','js/data.json').decode().splitlines():
        header,path=line.split('\t',1);mode,kind,object_sha=header.split()
        if mode in {'100644','100755'} and kind=='blob' and object_sha==blob:
            return dict(evidence_kind='identical_blob_public_push',source_blob_sha1=blob,published_head=head,published_path=path)
    return None


def build(base,out,repo=None):
    repo=repo or base/'geek-git-g111'
    evidence=base/'geek-git-evidence-g111';mb=(evidence/'manifest.json').read_bytes();bundle=json.loads(mb)
    checked(evidence/bundle['file'],bundle['sha256'])
    git(repo,'fsck','--full','--no-reflogs')
    parent=json.loads(Path(__file__).with_name('results-g110.json').read_text());root=base/'geek-publication-audit-g110-v1'
    report=json.loads(checked(root/'report.json',parent['report_sha256']))
    rows=json.loads(checked(root/'witnesses.json',report['artifacts']['witnesses.json']))
    events=[]
    for sha in report['event_sha256']:
        event=json.loads(checked(root/'events'/sha,sha));events.append(event|dict(_source_sha256=sha))
    events.sort(key=lambda e:(datetime.fromisoformat(e['created_at']),e['id']))
    extensions=[]
    for row in rows:
        if row['status']!='push_precedes_committer_time':continue
        data=checked(base/'geek-history-g108/objects'/row['source_sha256'],row['source_sha256'])
        for event in events:
            if datetime.fromisoformat(event['created_at'])<datetime.fromisoformat(row['committer_at']):continue
            found=proof(repo,row['revision'],data,event)
            if found is None:continue
            extension=dict(revision=row['revision'],source_sha256=row['source_sha256'],
                source_status=row['status'],source_committer_at=row['committer_at'],
                event_id=event['id'],source_event_sha256=event['_source_sha256'],available_at=event['created_at'],**found)
            extensions.append(extension)
            row.update(original_status=row['status'],status='later_publication_witness',available_at=event['created_at'],
                event_id=event['id'],source_event_sha256=event['_source_sha256'],evidence_kind=found['evidence_kind'])
            break
    out.mkdir(parents=True,exist_ok=True)
    for name,value in [('witnesses.json',rows),('extensions.json',extensions)]:
        (out/name).write_text(json.dumps(value,indent=2)+'\n')
    result=dict(version='geek-publication-extension-v1',implementation_sha256=digest(Path(__file__).read_bytes()),
        parent_report_sha256=parent['report_sha256'],git_bundle_manifest_sha256=digest(mb),git_bundle_sha256=bundle['sha256'],
        git_fsck_passed=True,extensions=len(extensions),evidence_kinds=dict(Counter(e['evidence_kind'] for e in extensions)),
        candidates=len(rows),published_snapshots=sum(r['available_at'] is not None for r in rows),
        witnessed_player_states=sum(r['players'] for r in rows if r['available_at'] is not None),
        finalized_labels_admitted=0,training_admitted=False,gt_changed=False,production_changed=False,
        limitations=['later_witness_may_be_less_fresh','identical_blob_proves_bytes_not_original_commit_publication',
            'unmodified_clock_conflicts_remain_in_parent_gate','no_deadline_or_field_admission'],
        artifacts={n:digest((out/n).read_bytes()) for n in ('witnesses.json','extensions.json')})
    (out/'report.json').write_text(json.dumps(result,indent=2)+'\n');return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--repo',type=Path)
    a=p.parse_args();print(json.dumps(build(a.base,a.out,a.repo),indent=2))
