"""Extract literal INSERT data from archived SQL without executing SQL statements."""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import re

import pandas as pd

from experiments.data_ground_truth.differential_audit import quality
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked

TABLES=('player_match','player_season','fixture','player','team')
TOKEN=re.compile(r'''\s*(NULL|[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?|'(?:[^']|'')*'|"(?:[^"]|"")*")\s*(,|$)''',re.I)


def statements(text: str):
    buffer=[];quote=None;i=0
    while i<len(text):
        c=text[i]
        if quote:
            buffer.append(c)
            if c==quote:
                if i+1<len(text) and text[i+1]==quote:
                    buffer.append(c);i+=2;continue
                quote=None
        elif text[i:i+2]=='--':
            end=text.find('\n',i)
            i=len(text) if end<0 else end
            buffer.append(' ');continue
        elif c in "'\"":
            quote=c;buffer.append(c)
        elif c==';':
            statement=''.join(buffer).strip();buffer=[]
            if statement:yield statement
        else:buffer.append(c)
        i+=1
    if quote or ''.join(buffer).strip():
        raise ValueError('unterminated SQL statement or string')


def literals(text: str):
    result=[];pos=0
    while pos<len(text):
        match=TOKEN.match(text,pos)
        if not match:raise ValueError('nonliteral SQL value')
        value,separator=match.groups()
        if value.upper()=='NULL':value=None
        elif value[0] in "'\"":value=value[1:-1].replace(value[0]*2,value[0])
        else:value=float(value) if any(c in value.lower() for c in '.e') else int(value)
        if isinstance(value,float) and not math.isfinite(value):
            raise ValueError('nonfinite SQL literal')
        result.append(value);pos=match.end()
        if not separator:break
        if pos==len(text):raise ValueError('trailing SQL comma')
    return result


def extract(text: str):
    tables={t:[] for t in TABLES};ignored=Counter()
    for statement in statements(text):
        insert=re.fullmatch(r'INSERT\s+INTO\s+(\w+)\s*\(([\w,\s]+)\)\s*VALUES\s*\((.*)\)',statement,re.I|re.S)
        if not insert:
            if statement.split()[0].lower()=='insert':raise ValueError('unsupported SQL insert')
            ignored[statement.split()[0].lower()]+=1;continue
        table,columns,values=insert.groups()
        if table not in TABLES:ignored['insert_other_table']+=1;continue
        names=[x.strip() for x in columns.split(',')];values=literals(values)
        if len(names)!=len(values) or len(set(names))!=len(names):
            raise ValueError('invalid SQL literal row')
        tables[table].append(dict(zip(names,values)))
    return {k:pd.DataFrame(v) for k,v in tables.items()},dict(ignored)


def build(root: Path):
    manifest=json.loads((root/'manifest.json').read_text())
    record=next(r for r in manifest['records'] if r['path']=='Differential/Database/DiffGenTestData_11_38.sql')
    data=checked(root/'objects'/record['sha256'],record['sha256'])
    tables,ignored=extract(data.decode('utf-8-sig'))
    dedup={}
    for table,frame in tables.items():
        clean=frame.drop_duplicates();dedup[table]=len(frame)-len(clean);tables[table]=clean
    report=dict(version='sql-literal-archive-v1',source_sha256=digest(data),ignored_statements=ignored,
        exact_duplicate_rows=dedup,seasons=quality(tables),
        status='pre_transformation_literal_data_unreconciled',sql_executed=False)
    dest=root/'sql-literals';dest.mkdir(parents=True,exist_ok=True)
    artifacts={}
    for table,frame in tables.items():
        # Retain original literal rows separately from training; no predictions exported.
        frame=frame[[c for c in frame if not c.startswith(('pred_','c_','diff_'))]].copy()
        frame['available_at']=None;frame['eligible_predeadline']=False;frame['eligible_training']=False
        path=dest/(table+'.csv');frame.to_csv(path,index=False)
        artifacts[table]=dict(rows=len(frame),sha256=digest(path.read_bytes()))
    report['artifacts']=artifacts
    (dest/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--root',type=Path,required=True)
    args=ap.parse_args();print(json.dumps(build(args.root),indent=2))


if __name__=='__main__':main()
