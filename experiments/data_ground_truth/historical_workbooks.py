"""Inspect pinned workbook XML without running macros, formulas or external links."""
from __future__ import annotations
import argparse
from collections import Counter
import io
import json
from pathlib import Path, PurePosixPath
import posixpath
import xml.etree.ElementTree as ET
import zipfile
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked

REPO='lifebeyondfife/FantasyFootball'
PIN='b3a43a31d688b4ca62ecea0077a21ae36b52cbc6'
NS={'x':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
REL='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
METRICS={'Ordered by Points Scored':'points_aggregate_unresolved_period',
         'Ordered by Value':'value_unresolved_definition',
         'Ordered by Popularity':'popularity_unresolved_snapshot'}


def inspect(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names=z.namelist()
        if len(names)!=len(set(names)):raise ValueError('duplicate ZIP members')
        if sum(x.file_size for x in z.infolist())>20_000_000:raise ValueError('oversized workbook')
        strings=[]
        if 'xl/sharedStrings.xml' in names:
            strings=[''.join(t.text or '' for t in s.findall('.//x:t',NS))
                     for s in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('x:si',NS)]
        relationships={r.attrib['Id']:r.attrib for r in ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
        result=[]
        for sheet in ET.fromstring(z.read('xl/workbook.xml')).findall('x:sheets/x:sheet',NS):
            name=sheet.attrib['name']
            if name not in METRICS:raise ValueError('unreviewed worksheet')
            rel=relationships[sheet.attrib['{'+REL+'}id']]
            if rel.get('TargetMode')=='External':raise ValueError('external worksheet forbidden')
            target=rel['Target']
            path=posixpath.normpath('xl/'+target)
            if PurePosixPath(target).is_absolute() or not path.startswith('xl/worksheets/'):raise ValueError('unsafe worksheet target')
            rows=[];incomplete=0
            for row in ET.fromstring(z.read(path)).findall('x:sheetData/x:row',NS):
                number=int(row.attrib['r'])
                if number<20:continue
                cells={}
                for c in row:
                    address=c.attrib['r'];column=address.rstrip('0123456789')
                    if column not in 'ABCDE' or len(column)!=1:continue
                    v=c.find('x:v',NS);value=v.text if v is not None else None
                    if c.attrib.get('t')=='s' and value is not None:
                        i=int(value)
                        if i<0 or i>=len(strings):raise ValueError('invalid shared string')
                        value=strings[i]
                    elif c.attrib.get('t')=='inlineStr':value=''.join(t.text or '' for t in c.findall('.//x:t',NS))
                    f=c.find('x:f',NS)
                    cells[column]=dict(address=address,value=value,formula=f.text if f is not None else None)
                if cells.get('E',{}).get('value') not in ('GK','DF','MF','FW'):continue
                if any(cells.get(c,{}).get('value') is None for c in 'ABCDE'):incomplete+=1
                rows.append(dict(row=number,cells=cells))
            result.append(dict(sheet=name,xml_path=path,metric=METRICS[name],rows=rows,incomplete_rows=incomplete))
        return result


def literal_signature(row):
    cells=row['cells']
    if any(cells.get(c,{}).get('value') is None or cells[c]['formula'] is not None for c in 'ABCDE'):return None
    return tuple(cells[c]['value'].strip() for c in 'ABCDE')


def build(root,out):
    manifest_bytes=(root/'manifest.json').read_bytes();manifest=json.loads(manifest_bytes)
    tables=[];summaries=[]
    for source in manifest['records']:
        if source['repository']!=REPO or source['revision']!=PIN:raise ValueError('unexpected workbook source')
        data=checked(root/'objects'/source['sha256'],source['sha256'])
        if len(data)!=source['bytes']:raise ValueError('source size mismatch')
        if not source['path'].endswith('.xlsm'):continue
        for sheet in inspect(data):
            table=dict(source_path=source['path'],source_sha256=source['sha256'],**sheet);tables.append(table)
            signatures=[literal_signature(r) for r in sheet['rows']];valid=[s for s in signatures if s is not None]
            identities=Counter((s[0],s[1],s[4]) for s in valid)
            summaries.append(dict(source_path=source['path'],sheet=sheet['sheet'],metric=sheet['metric'],
                player_rows=len(signatures),literal_complete_rows=len(valid),incomplete_rows=sheet['incomplete_rows'],
                observed_clubs=len({s[1] for s in valid}),duplicate_name_club_role_groups=sum(n>1 for n in identities.values()),
                formula_cells=sum(c['formula'] is not None for r in sheet['rows'] for c in r['cells'].values())))
    overlaps=[]
    for i,a in enumerate(tables):
        for b in tables[i+1:]:
            if a['sheet']!=b['sheet'] or a['source_path']==b['source_path']:continue
            aa=Counter(s for r in a['rows'] if (s:=literal_signature(r)) is not None)
            bb=Counter(s for r in b['rows'] if (s:=literal_signature(r)) is not None)
            overlaps.append(dict(source_a=a['source_path'],source_b=b['source_path'],sheet=a['sheet'],
                exact_literal_rows_in_common=sum((aa&bb).values()),identical_literal_multiset=aa==bb))
    out.mkdir(parents=True,exist_ok=True)
    (out/'tables.json').write_text(json.dumps(tables,indent=2)+'\n')
    report=dict(version='historical-workbook-evidence-v1',manifest_sha256=digest(manifest_bytes),
        implementation_sha256=digest(Path(__file__).read_bytes()),source_files=len(manifest['records']),
        source_bytes=sum(r['bytes'] for r in manifest['records']),workbooks=len({t['source_path'] for t in tables}),
        worksheets=len(tables),player_sheet_rows=sum(s['player_rows'] for s in summaries),sheets=summaries,overlaps=overlaps,
        new_FPL_gameweek_labels=0,new_complete_FPL_seasons=0,eligible_predeadline=False,training_admitted=False,
        production_changed=False,macros_executed=False,formulas_evaluated=False,external_links_followed=False,
        limitations=['workbook_filename_does_not_establish_observation_or_points_period',
          'sheet_rows_are_not_unique_players_across_sheets',
          'names_without_official_codes_do_not_establish_cross_source_identity',
          'overlap_is_not_proof_of_full_sheet_equivalence_or_creation_date',
          'observed_prices_and_aggregates_are_not_gameweek_labels_or_causal_inputs'],
        artifacts={'tables.json':digest((out/'tables.json').read_bytes())})
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();r=build(a.root,a.out);print(json.dumps({k:v for k,v in r.items() if k not in ('sheets','overlaps')}))


if __name__=='__main__':main()
