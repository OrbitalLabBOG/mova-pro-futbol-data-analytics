"""Bind archived player snapshots to exact public GitHub push witnesses."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime
import gzip
import io
import json
from pathlib import Path
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked

REPO='jokecamp/epl-fantasy-geek'
REPO_ID=23294266
EARLY='a0422afb2dce2fdd13644b93042cb22e45e42fe3'


def public_push(event):
    repo=event.get('repo',{})
    return (event.get('type')=='PushEvent' and event.get('public') is True and
        repo.get('id')==REPO_ID and repo.get('name','').lower()==REPO)


def witness(commit,committer_at,events):
    matched=[e for e in events if public_push(e) and
        (e['payload'].get('head')==commit or commit in [c.get('sha') for c in e['payload'].get('commits',[])])]
    result=dict(status='no_exact_public_push_in_scanned_hours',available_at=None,eligible_predeadline=False)
    if not matched:
        return result
    event=min(matched,key=lambda e:datetime.fromisoformat(e['created_at']))
    if datetime.fromisoformat(event['created_at'])<datetime.fromisoformat(committer_at):
        return result|dict(status='push_precedes_committer_time',event_id=event['id'])
    return result|dict(status='exact_public_push_witness',available_at=event['created_at'],
        event_id=event['id'],source_event_sha256=event['_source_sha256'])


def build(base,out):
    directory=Path(__file__).parent
    prior=json.loads((directory/'results-g109.json').read_text())
    parent=base/'geek-context-g109-v1';checked(parent/'report.json',prior['report_sha256'])
    context=json.loads(checked(parent/'snapshots.json',prior['audit']['artifacts']['snapshots.json']))
    selected=[c for c in context if c['candidate_season']=='2015-16' or c['revision']==EARLY]
    g108=json.loads((directory/'results-g108.json').read_text())
    commits=[];metadata_hashes={}
    for name in ('data-history.json','data-history-2.json'):
        data=checked(base/'historical-discovery-g108'/name,g108['audit']['history_metadata_sha256'][name])
        metadata_hashes[name]=digest(data);commits.extend(json.loads(data))
    metadata={c['sha']:c for c in commits}
    root=base/'geek-publication-g110';mb=(root/'manifest.json').read_bytes();manifest=json.loads(mb)
    if manifest['errors']:
        raise ValueError('acquisition has errors')
    instants=[datetime.fromisoformat(metadata[c['revision']]['commit']['committer']['date']) for c in selected]
    required={'https://data.gharchive.org/'+d.strftime('%Y-%m-%d-')+str(d.hour)+'.json.gz' for d in instants}
    required.update({'https://data.gharchive.org/2014-08-24-23.json.gz','https://data.gharchive.org/2014-08-25-0.json.gz'})
    urls=[r['url'] for r in manifest['records']]
    if len(urls)!=len(set(urls)) or set(urls)!=required:
        raise ValueError('archive hour set differs from requested candidate scope')
    out.mkdir(parents=True,exist_ok=True);(out/'events').mkdir(exist_ok=True)
    events=[];hours=[]
    for record in manifest['records']:
        data=checked(root/'objects'/record['sha256'],record['sha256'])
        if len(data)!=record['bytes']:
            raise ValueError('archive size mismatch')
        scanned=0;relevant=0
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
            for line in stream:
                scanned+=1
                if b'23294266' not in line and b'epl-fantasy-geek' not in line.lower():
                    continue
                event=json.loads(line)
                if not public_push(event):
                    continue
                sha=digest(line);(out/'events'/sha).write_bytes(line)
                events.append(event|dict(_source_sha256=sha));relevant+=1
        hours.append(dict(url=record['url'],sha256=record['sha256'],bytes=record['bytes'],scanned_events=scanned,public_push_events=relevant))
        if len(hours)%15==0:print('scanned',len(hours),'/',len(manifest['records']),'hours',flush=True)
    rows=[]
    for c in selected:
        data=checked(base/'geek-history-g108/objects'/c['sha256'],c['sha256'])
        if not data:
            raise ValueError('empty target snapshot')
        committer=metadata[c['revision']]['commit']['committer']['date']
        rows.append(dict(revision=c['revision'],source_sha256=c['sha256'],candidate_season=c['candidate_season'],
            players=c['players'],committer_at=committer,**witness(c['revision'],committer,events)))
    for name,value in [('hours.json',hours),('witnesses.json',rows)]:
        (out/name).write_text(json.dumps(value,indent=2)+'\n')
    report=dict(version='geek-publication-v1',implementation_sha256=digest(Path(__file__).read_bytes()),
        parent_report_sha256=prior['report_sha256'],manifest_sha256=digest(mb),commit_metadata_sha256=metadata_hashes,
        scanned_hours=len(hours),compressed_bytes=sum(h['bytes'] for h in hours),scanned_events=sum(h['scanned_events'] for h in hours),
        public_push_events=len(events),candidates=len(rows),statuses=dict(Counter(r['status'] for r in rows)),
        witnessed_player_states=sum(r['players'] for r in rows if r['status']=='exact_public_push_witness'),
        finalized_labels_admitted=0,training_admitted=False,gt_changed=False,production_changed=False,
        limitations=['2015_16_candidate_committer_hours_plus_three_early_hours_only','no_event_not_proof_of_nonpublication',
            'exact_commit_witness_only_no_ancestor_inference','2014_timeline_schema_not_admitted_as_modern_event',
            'publication_upper_bound_not_api_capture_time','no_deadline_selection_or_training_admission'],
        artifacts={n:digest((out/n).read_bytes()) for n in ('hours.json','witnesses.json')},
        event_sha256=sorted({e['_source_sha256'] for e in events}))
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.base,a.out),indent=2))
