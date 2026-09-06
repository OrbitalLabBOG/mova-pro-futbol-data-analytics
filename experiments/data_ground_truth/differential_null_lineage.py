"""Audit missing outcomes separately from forecast presence; never impute NULL."""
from __future__ import annotations
import argparse
import json
import sqlite3
from pathlib import Path
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked

DB_SHA = 'e4f1e637702f69cfa513a5719b05f87bb0aab47ddd2cd4864b40d567c1ac9f80'
OUTCOMES = ('minutes', 'total', 'goals', 'assists', 'bonus', 'conceded',
            'pen_sav', 'pen_miss', 'yellow', 'red', 'saves', 'own_goals')


def summarize(rows):
    unknown = [r for r in rows if r['minutes'] is None]
    return dict(rows=len(rows), unknown_minutes=len(unknown),
        unknown_minutes_with_forecast=sum(r['has_forecast'] for r in unknown),
        unknown_minutes_without_any_selected_outcome=sum(all(r[k] is None for k in OUTCOMES) for r in unknown),
        unknown_minutes_gameweeks=sorted({r['gameweek'] for r in unknown}),
        known_minutes_missing_points=sum(r['minutes'] is not None and r['total'] is None for r in rows),
        new_observed_labels=0, null_to_zero_admitted=False, training_admitted=False,
        limitations=['forecast_presence_is_not_an_observed_outcome',
                    'source_code_does_not_prove_which_path_created_each_archived_row',
                    'selected_outcome_columns_not_a_complete_row_provenance_trace'])


def build(base, out):
    db=base/'raw-history-differential/objects'/DB_SHA;checked(db,DB_SHA)
    root=base/'differential-null-lineage-g97';manifest=json.loads((root/'manifest.json').read_text())
    source=manifest['records'][0]
    if source['path'] != 'Differential/src/com/pennas/fpl/process/ProcessPlayer.java' or source['revision'] != '6bb3366343998ac016f6a3120e9cba9a3f0037eb':
        raise ValueError('unexpected code provenance')
    code=root/'objects'/source['sha256'];checked(code,source['sha256'])
    lines=code.read_text().splitlines()
    evidence=[dict(line=i+1,text=lines[i].strip()) for i in range(1115,1131)]
    if not any('db.replace(t_player_match, null, updatePM)' in r['text'] for r in evidence):
        raise ValueError('reviewed source block changed')
    with sqlite3.connect(f'file:{db}?mode=ro&immutable=1',uri=True) as conn:
        conn.execute('pragma trusted_schema=OFF');conn.execute('pragma query_only=ON')
        if conn.execute('pragma quick_check').fetchone()[0] != 'ok':raise ValueError('invalid database')
        if conn.execute("select type from sqlite_master where name='player_match'").fetchone()!=('table',):raise ValueError('expected physical table')
        conn.row_factory=sqlite3.Row
        # Only forecast presence is retained for provenance, never its numerical prediction.
        rows=[dict(r) for r in conn.execute('select player_player_id,fixture_id,gameweek,'+','.join(OUTCOMES)+',pred_total_pts is not null as has_forecast from player_match where season=14 order by player_player_id,fixture_id')]
    report=summarize(rows)
    out.mkdir(parents=True,exist_ok=True)
    artifacts={'unknown_rows.json':[r for r in rows if r['minutes'] is None or r['total'] is None], 'code_evidence.json':evidence}
    for name,value in artifacts.items():(out/name).write_text(json.dumps(value,indent=2)+'\n')
    report.update(version='differential-null-lineage-v1',database_sha256=DB_SHA,
        source=source,source_manifest_sha256=digest((root/'manifest.json').read_bytes()),
        implementation_sha256=digest(Path(__file__).read_bytes()),
        artifacts={n:digest((out/n).read_bytes()) for n in artifacts})
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.base,a.out),indent=2))
