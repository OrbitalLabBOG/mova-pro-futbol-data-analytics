"""Extract pinned official PDFs and audit schedule populations without inventing time evidence."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import gzip
import lzma
import json
from pathlib import Path
import re


def sha(data):
    return hashlib.sha256(data).hexdigest()


def checked(path, expected):
    data = path.read_bytes()
    if sha(data) != expected:
        raise ValueError('source hash mismatch')
    return data


def extract(root, out):
    import pymupdf
    if pymupdf.VersionBind != '1.26.4':
        raise ValueError('pymupdf 1.26.4 required for reproducible extraction')
    out.mkdir(parents=True, exist_ok=True)
    result = []
    for name in ('fa-2013-14', 'pl-fdr-2025-26'):
        source_bytes = (root/(name+'.json')).read_bytes(); source = json.loads(source_bytes)
        data = checked(root/(name+'.pdf'), source['sha256'])
        if len(data) != source['bytes']:
            raise ValueError('PDF size mismatch')
        document = pymupdf.open(stream=data, filetype='pdf')
        pages = []
        for page in document:
            pages.append(dict(text=page.get_text('text', sort=True), words=page.get_text('words'),
                              fills=[dict(rect=list(d['rect']), color=d['fill']) for d in page.get_drawings() if d['fill'] is not None]))
        payload = (json.dumps(pages, indent=2)+'\n').encode(); (out/(name+'.json')).write_bytes(payload)
        result.append(dict(name=name, source=source, source_record_sha256=sha(source_bytes),
                           extracted_sha256=sha(payload), pages=len(pages),
                           pdf_creation_date=document.metadata.get('creationDate'),
                           pdf_modification_date=document.metadata.get('modDate')))
    report = dict(version='official-calendar-pdf-extraction-v1', pymupdf_version=pymupdf.VersionBind,
                  implementation_sha256=sha(Path(__file__).read_bytes()), sources=result)
    (out/'manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def fixtures_2013(pages):
    rows=[]
    pattern=re.compile(r'^(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})\s+(.+?)\s+v\s+(.+?)$')
    for page_number,page in enumerate(pages):
        for line_number,line in enumerate(page['text'].splitlines()):
            line=' '.join(line.split())
            if not line or line in ('Premier League Fixtures','2013/14 Season'):
                continue
            match=pattern.fullmatch(line)
            if not match:
                raise ValueError('unparsed fixture line: '+line[:100])
            date,clock,home,away=match.groups()
            dt=datetime.strptime(date+' '+clock,'%d/%m/%Y %H:%M')
            if not datetime(2013,8,1)<=dt<datetime(2014,6,1):
                raise ValueError('fixture outside season')
            rows.append(dict(home=home,away=away,source_local_datetime=dt.isoformat(),
                             timezone=None,kickoff_time=None,gw=None,page=page_number+1,line=line_number+1))
    validate_pairs(rows)
    return rows


def validate_pairs(rows):
    clubs={r['home'] for r in rows}|{r['away'] for r in rows}
    pairs=[(r['home'],r['away']) for r in rows]
    expected={(a,b) for a in clubs for b in clubs if a!=b}
    if len(clubs)!=20 or len(rows)!=380 or len(set(pairs))!=380 or set(pairs)!=expected:
        raise ValueError('incomplete or duplicate double round robin')


def center(word):
    return ((word[0]+word[2])/2,(word[1]+word[3])/2)


def fill_at(point, fills):
    colors={tuple(round(c,6) for c in f['color']) for f in fills
            if f['rect'][0]<point[0]<f['rect'][2] and f['rect'][1]<point[1]<f['rect'][3]}
    if len(colors)!=1:
        raise ValueError('ambiguous or missing cell fill')
    return next(iter(colors))


def fdr_matrix(page):
    words=page['words']; fills=page['fills']
    headers=[w for w in words if re.fullmatch(r'GW\d+',w[4])]
    if sorted(int(w[4][2:]) for w in headers)!=list(range(1,39)):
        raise ValueError('FDR headers must cover GW1-38')
    labels=[w for w in words if re.fullmatch('[A-Z]{3}',w[4]) and w[2]<min(h[0] for h in headers)]
    if len(labels)!=40 or set(Counter(w[4] for w in labels).values())!={2}:
        raise ValueError('FDR row labels mismatch')
    legend={}
    for w in words:
        if w[4] in ('1','2','3','4','5'):
            color=fill_at(center(w),fills)
            if color in legend:raise ValueError('ambiguous legend color')
            legend[color]=int(w[4])
    if set(legend.values())!={1,2,3,4,5}:raise ValueError('incomplete FDR legend')
    rows=[]
    for label in labels:
        y=center(label)[1]
        header_y=max(center(h)[1] for h in headers if center(h)[1]<y)
        columns=sorted([h for h in headers if center(h)[1]==header_y],key=lambda h:center(h)[0])
        if len(columns)!=19:raise ValueError('FDR header block mismatch')
        row_words=[w for w in words if abs(center(w)[1]-y)<1 and w[0]>label[2]]
        cells={int(h[4][2:]):[] for h in columns}
        for w in row_words:
            header=min(columns,key=lambda h:abs(center(h)[0]-center(w)[0]))
            if abs(center(header)[0]-center(w)[0])>10:raise ValueError('FDR word outside cell')
            cells[int(header[4][2:])].append(w)
        for gw,cell in cells.items():
            cell.sort(key=lambda w:w[0]); text=' '.join(w[4] for w in cell)
            match=re.fullmatch(r'([A-Z]{3}) \(([HA])\)',text)
            if not match:raise ValueError('malformed FDR cell: '+text)
            opponent,venue=match.groups();color=fill_at(center(cell[0]),fills)
            rows.append(dict(club=label[4],gw=gw,opponent=opponent,venue=venue,
                             fdr=legend.get(color),pdf_fill_rgb=color,word_boxes=[w[:4] for w in cell]))
    validate_matrix(rows)
    return rows,legend


def validate_matrix(rows):
    indexed={(r['club'],r['gw']):r for r in rows};clubs={r['club'] for r in rows}
    if len(clubs)!=20 or len(rows)!=760 or len(indexed)!=760 or set(indexed)!={(c,g) for c in clubs for g in range(1,39)}:
        raise ValueError('incomplete FDR population')
    fixtures=[]
    for r in rows:
        other=indexed.get((r['opponent'],r['gw']))
        if r['venue'] not in ('H','A') or other is None or other['opponent']!=r['club'] or other['venue']==r['venue']:
            raise ValueError('FDR reciprocity mismatch')
        if r['venue']=='H':fixtures.append(dict(home=r['club'],away=r['opponent']))
    validate_pairs(fixtures)


def reference_comparison(matrix, base):
    selection_bytes=(base/'publication-selection-v1/report.json').read_bytes();selection=json.loads(selection_bytes)
    candidates=json.loads(checked(base/'publication-selection-v1/nominal_deadline_candidates.json',selection['artifacts']['nominal_deadline_candidates.json']))
    candidates=[c for c in candidates if c['season']=='2025-26' and c['gw']==1]
    if len(candidates)!=1:raise ValueError('ambiguous team reference')
    candidate=candidates[0];raw=checked(base/'raw-bootstrap-snapshots/objects'/candidate['sha256'],candidate['sha256'])
    decoder=lzma.LZMADecompressor(memlimit=256*1024*1024);payload=decoder.decompress(raw,max_length=32*1024*1024+1)
    if len(payload)>32*1024*1024 or not decoder.eof or decoder.unused_data:raise ValueError('invalid team reference compression')
    boot=json.loads(payload);teams={t['id']:t['short_name'] for t in boot['teams']}
    if len(teams)!=20 or len(set(teams.values()))!=20:raise ValueError('team reference population mismatch')
    report_bytes=(base/'fixture-history-audit-v1/report.json').read_bytes();report=json.loads(report_bytes)
    versions=json.loads(checked(base/'fixture-history-audit-v1/versions.json',report['artifacts']['versions.json']))
    latest=max((v for v in versions if v['season']=='2025-26'),key=lambda v:datetime.fromisoformat(v['committer_at']))
    fixtures=json.loads(gzip.decompress(checked(base/'fixture-history-audit-v1/objects'/latest['normalized_sha256'],latest['normalized_sha256'])))
    indexed={(teams[f['team_h']],teams[f['team_a']]):f for f in fixtures}
    pdf={(r['club'],r['opponent']) for r in matrix if r['venue']=='H'}
    if len(indexed)!=380 or len(fixtures)!=380 or pdf!=set(indexed):raise ValueError('official fixture identity disagreement')
    differences=[]
    for r in matrix:
        key=(r['club'],r['opponent']) if r['venue']=='H' else (r['opponent'],r['club'])
        f=indexed[key];field='team_h_difficulty' if r['venue']=='H' else 'team_a_difficulty'
        if r['gw']!=f['event'] or r['fdr']!=f[field]:
            differences.append(dict(club=r['club'],opponent=r['opponent'],venue=r['venue'],fixture=f['id'],
                                    pdf_gw=r['gw'],reference_gw=f['event'],pdf_fdr=r['fdr'],reference_fdr=f[field]))
    return dict(selection_report_sha256=sha(selection_bytes),team_bootstrap_sha256=candidate['sha256'],
                fixture_report_sha256=sha(report_bytes),fixture_reference=latest,
                verified_fixture_pairs=380,compared_team_observations=len(matrix),
                changed_gw_observations=sum(d['pdf_gw']!=d['reference_gw'] for d in differences),
                changed_fdr_observations=sum(d['pdf_fdr']!=d['reference_fdr'] for d in differences),
                differences=differences,comparison_kind='retrospective_diagnostic_not_feature_repair')


def audit(extracted, out, base):
    manifest_bytes=(extracted/'manifest.json').read_bytes();manifest=json.loads(manifest_bytes)
    sources={r['name']:r for r in manifest['sources']}
    if set(sources)!={'fa-2013-14','pl-fdr-2025-26'} or len(manifest['sources'])!=2:
        raise ValueError('unexpected PDF source inventory')
    pages={name:json.loads(checked(extracted/(name+'.json'),r['extracted_sha256'])) for name,r in sources.items()}
    if len(pages['pl-fdr-2025-26'])!=1:raise ValueError('FDR PDF must be one page')
    fixtures=fixtures_2013(pages['fa-2013-14']);matrix,legend=fdr_matrix(pages['pl-fdr-2025-26'][0])
    comparison=reference_comparison(matrix,base)
    out.mkdir(parents=True,exist_ok=True);artifacts={}
    for name,rows in [('fixtures-2013-14.json',fixtures),('fdr-2025-26.json',matrix)]:
        for row in rows:row.update(available_at=None,eligible_training=False,eligible_replay=False)
        data=(json.dumps(rows,indent=2)+'\n').encode();(out/name).write_bytes(data);artifacts[name]=sha(data)
    comparison_bytes=(json.dumps(comparison,indent=2)+'\n').encode();(out/'reference-comparison.json').write_bytes(comparison_bytes);artifacts['reference-comparison.json']=sha(comparison_bytes)
    result=dict(version='official-calendar-pdf-audit-v1',extraction_manifest_sha256=sha(manifest_bytes),
                implementation_sha256=sha(Path(__file__).read_bytes()),fixtures_2013_14=len(fixtures),
                fdr_cells_2025_26=len(matrix),fdr_ratings=dict(Counter(str(r['fdr']) for r in matrix)),
                unclassified_fdr_colors=sum(r['fdr'] is None for r in matrix),
                reference_comparison={k:v for k,v in comparison.items() if k!='differences'},
                legend=[dict(rgb=k,rating=v) for k,v in sorted(legend.items(),key=lambda x:x[1])],
                artifacts=artifacts,production_changed=False,training_admitted=False,replay_admitted=False,
                limitations=['PDF_creation_and_HTTP_modified_dates_are_not_publication_proofs',
                             '2013_local_clocks_have_no_explicit_timezone_or_FPL_GW_mapping',
                             '2025_FDR_is_a_single_preseason_version_not_a_time_series',
                             'source_schedule_not_final_fixture_results'])
    (out/'report.json').write_text(json.dumps(result,indent=2)+'\n');return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['extract','audit'])
    p.add_argument('--source',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--base-root',type=Path);a=p.parse_args()
    if a.mode=='audit' and a.base_root is None:p.error('--base-root required for audit')
    result=extract(a.source,a.out) if a.mode=='extract' else audit(a.source,a.out,a.base_root)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
