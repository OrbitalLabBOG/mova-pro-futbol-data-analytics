"""Inventory Footieviz raw/history captures and compare observed match rows."""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3

from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked

BASELINE = '21c74e98562268738a7b520b0518e6a48068f0b3117dc0c2e33660016f4f515e'


def sqlite_counts(path):
    connection = sqlite3.connect(path.resolve().as_uri()+'?mode=ro&immutable=1', uri=True)
    try:
        connection.execute('pragma trusted_schema=off')
        connection.execute('pragma query_only=on')
        if connection.execute('pragma quick_check').fetchall() != [('ok',)]:
            raise ValueError('SQLite integrity failure')
        tables = connection.execute("select name,sql from sqlite_master where type='table'").fetchall()
        if any('virtual table' in (sql or '').lower() for _,sql in tables):
            raise ValueError('virtual table not admitted')
        return {name:connection.execute('select count(*) from "'+name.replace('"','""')+'"').fetchone()[0] for name,_ in sorted(tables)}
    finally:
        connection.close()


def compare(players, baseline):
    known = {p['id']:p for p in baseline}
    observations = []
    for player in players:
        prior = known.get(player['id'])
        identity_ok = prior is not None and prior['code']==player['code']
        lookup = {}
        if identity_ok:
            for row in prior['fixture_history']['all']:
                key=tuple(row[:3])
                if key in lookup:
                    raise ValueError('ambiguous baseline row')
                lookup[key]=row
        for row in player['fixture_history']['all']:
            if len(row)!=20:
                raise ValueError('invalid row width')
            other=lookup.get(tuple(row[:3]))
            observations.append(dict(element=player['id'],code=player['code'],source_row=row,
                status='identity_mismatch' if not identity_ok else ('missing_baseline_key' if other is None else 'paired'),
                baseline_row=other, different_columns=[i for i in range(20) if row[i]!=other[i]] if other else None,
                eligible_training=False,final_observation_proven=False))
    return observations


def build(base,out):
    baseline=json.loads(checked(base/'early-fpl-json-g88/objects'/BASELINE,BASELINE))
    entries=[];observations=[];manifests={}
    for directory in ('footieviz-source-g106','footieviz-history-g106'):
        root=base/directory;payload=(root/'manifest.json').read_bytes();manifests[directory]=digest(payload)
        for record in json.loads(payload)['records']:
            data=checked(root/'objects'/record['sha256'],record['sha256'])
            if len(data)!=record['bytes']:
                raise ValueError('source size mismatch')
            entry={k:record[k] for k in ('path','revision','sha256','bytes')}
            if record['path'].endswith('.db'):
                entry.update(kind='sqlite',tables=sqlite_counts(root/'objects'/record['sha256']))
            elif record['path']=='raw_data.json':
                try:
                    parsed=json.loads(data)
                except json.JSONDecodeError as error:
                    entry.update(kind='invalid_json',error_offset=error.pos)
                else:
                    players=parsed if isinstance(parsed,list) else [parsed]
                    rows=compare(players,baseline)
                    # Profiles with no match history remain annual/state evidence only.
                    entry.update(kind='profiles',profiles=len(players),history_rows=len(rows),
                        annual_seasons=sorted({r[0] for p in players for r in p['season_history']}),
                        gameweeks=sorted({r['source_row'][1] for r in rows}))
                    observations.extend(dict(source_sha256=record['sha256'],**r) for r in rows)
            else:
                entry.update(kind='context_not_executed')
            entries.append(entry)
    out.mkdir(parents=True,exist_ok=True)
    for name,value in [('inventory.json',entries),('comparisons.json',observations)]:
        (out/name).write_text(json.dumps(value,indent=2)+'\n')
    paired=[r for r in observations if r['status']=='paired']
    report=dict(version='footieviz-source-audit-v1',implementation_sha256=digest(Path(__file__).read_bytes()),
        source_manifest_sha256=manifests,baseline_sha256=BASELINE,captured_records=len(entries),
        unique_contents=len({e['sha256'] for e in entries}),captured_bytes=sum(e['bytes'] for e in entries),
        kinds=dict(Counter(e['kind'] for e in entries)),sqlite_total_rows=sum(sum(e['tables'].values()) for e in entries if e['kind']=='sqlite'),
        history_rows=len(observations),comparison_statuses=dict(Counter(r['status'] for r in observations)),
        different_column_counts=dict(sorted(Counter(i for r in paired for i in r['different_columns']).items())),
        minute_conflicts=sum(3 in r['different_columns'] for r in paired),point_conflicts=sum(19 in r['different_columns'] for r in paired),
        new_complete_seasons=0,finalized_labels_admitted=0,training_admitted=False,gt_changed=False,production_changed=False,
        limitations=['path_history_on_default_branch_only','one_removed_database_commit_retained_in_source_evidence',
            'invalid_json_not_repaired','annual_totals_not_match_labels','source_file_date_not_publication_proof',
            'raw_date_gw_opponent_join_not_new_fixture_normalization'],
        artifacts={n:digest((out/n).read_bytes()) for n in ('inventory.json','comparisons.json')})
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(build(args.base,args.out),indent=2))
