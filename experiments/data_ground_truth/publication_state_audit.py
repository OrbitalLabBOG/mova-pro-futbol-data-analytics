"""Bind selected snapshot witnesses to typed states and quantify changes from G19."""
from __future__ import annotations
import argparse
from collections import Counter
import csv
import gzip
import io
import json
from pathlib import Path

from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked


def states(root):
    payload=(root/'report.json').read_bytes();report=json.loads(payload);rows={}
    for kind in ('player','manager'):
        name=kind+'_states.csv.gz'
        data=checked(root/name,report['artifacts'][name])
        for row in csv.DictReader(io.StringIO(gzip.decompress(data).decode())):
            key=(kind,row['season'],int(row['gw']),int(row['element']))
            if key in rows:raise ValueError('duplicate state identity')
            rows[key]=row
    if len(rows)!=report['rows']:raise ValueError('state row count mismatch')
    return report,digest(payload),rows


def build(selection_root:Path,state_root:Path,previous_state_root:Path,out:Path):
    selection_bytes=(selection_root/'report.json').read_bytes();selection=json.loads(selection_bytes)
    candidates=json.loads(checked(selection_root/'nominal_deadline_candidates.json',selection['artifacts']['nominal_deadline_candidates.json']))
    proofs=json.loads(checked(selection_root/'publication_witnesses.json',selection['artifacts']['publication_witnesses.json']))
    candidate_map={(c['season'],c['gw']):c for c in candidates};proof_map={(p['season'],p['gw']):p for p in proofs}
    if len(candidate_map)!=len(candidates) or len(proof_map)!=len(proofs):raise ValueError('duplicate selection key')
    report,report_hash,rows=states(state_root);previous,previous_hash,old=states(previous_state_root)
    if report['source_manifest_sha256']!=selection['manifest_sha256'] or report['candidate_sha256']!=selection['artifacts']['nominal_deadline_candidates.json']:
        raise ValueError('typed state selection mismatch')
    if report['reference_dataset_id']!=previous['reference_dataset_id']:raise ValueError('reference dataset changed')
    counts={s:Counter() for s in selection['seasons']};changes=Counter();unchanged=0;comparable=0
    for key,row in rows.items():
        kind,season,gw,_=key;c=candidate_map[(season,gw)];p=proof_map.get((season,gw))
        if row['source_sha256']!=c['sha256'] or row['deadline']!=c['deadline']:raise ValueError('selected state content/deadline mismatch')
        if row['eligible_training']!='False' or row['eligible_predeadline']!='False' or row['available_at']!='':raise ValueError('unexpected state admission')
        counts[season][kind+'_rows']+=1
        if p:
            if p['source_sha256']!=row['source_sha256'] or p['deadline']!=row['deadline'] or p['eligible_predeadline'] is not True:
                raise ValueError('state publication mismatch')
            counts[season]['verified_'+kind+'_rows']+=1
        if key in old:
            before=old[key]
            if before['source_sha256']==row['source_sha256']:
                if before!=row:raise ValueError('unchanged snapshot state drift')
                unchanged+=1
            else:
                comparable+=1
                changes.update(k for k in row if row[k]!=before[k])
    result=dict(version='publication-state-audit-v1',selection_report_sha256=digest(selection_bytes),state_report_sha256=report_hash,
        previous_state_report_sha256=previous_hash,implementation_sha256=digest(Path(__file__).read_bytes()),seasons={s:dict(c) for s,c in counts.items()},
        unchanged_snapshot_rows=unchanged,changed_snapshot_comparable_rows=comparable,added_keys=len(set(rows)-set(old)),removed_keys=len(set(old)-set(rows)),
        changed_field_counts=dict(changes),rejected_rows=report['rejected_rows'],
        training_admitted=False,production_changed=False)
    out.mkdir(parents=True,exist_ok=True);(out/'report.json').write_text(json.dumps(result,indent=2)+'\n');return result


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('selection-root','state-root','previous-state-root','out'):ap.add_argument('--'+name,type=Path,required=True)
    a=ap.parse_args();print(json.dumps(build(a.selection_root,a.state_root,a.previous_state_root,a.out),indent=2))


if __name__=='__main__':main()
