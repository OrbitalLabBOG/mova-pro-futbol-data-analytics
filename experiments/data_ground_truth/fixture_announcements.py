"""Extract dated official schedule statements without inferring historical publication."""
from __future__ import annotations
import argparse
from collections import Counter
import csv
from datetime import datetime,timezone
import gzip
import io
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo
from experiments.data_ground_truth.historical_rule_evidence import visible
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked

ARTICLES=[
 ('2533700','2021-22',2022,'15 Mar 2022','2022-03-15','BST','Fixture amendments for April-May 2022'),
 ('2562266','2021-22',2022,'04 Apr 2022','2022-04-04','BST',"May's broadcast picks and rescheduled fixtures"),
 ('3053298','2022-23',2023,'07 Feb 2023','2023-02-07','GMT','Two Premier League matches rearranged for March'),
 ('3053317','2022-23',2023,'07 Feb 2023','2023-02-07',None,'Arsenal and Liverpool given Double Gameweek 25'),
 ('3040501','2022-23',2023,'02 Feb 2023','2023-02-02',None,'How FA Cup and EFL Cup results will affect FPL managers')]
TEAM_SHA={'2021-22':'c1dd02ed25fe832ba7bf6ce846ac506a00a0f0babdacb6bf2a011dc9eaa8cfad',
          '2022-23':'be6a1fe120a61f9c441a0751ca177c933bcbf234c1d28d49b3cd8827ca18066b'}
DATE=re.compile(r'\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday) (\d{1,2}) (March|April|May)\b')
MONTH={'March':3,'April':4,'May':5}


def schedule(text,year,zone,teams):
    if zone not in ('GMT','BST') or zone not in text:raise ValueError('explicit reviewed timezone required')
    names='|'.join(re.escape(x) for x in sorted(teams,key=len,reverse=True))
    pattern=re.compile(r'(?P<time>\d{2}:\d{2})(?: GMT)? (?P<home>'+names+r') v (?P<away>'+names+r')(?!\w)(?: \([^)]*\))?(?P<condition>\*{1,2})?')
    dates=list(DATE.finditer(text));rows=[]
    for i,date in enumerate(dates):
        end=dates[i+1].start() if i+1<len(dates) else len(text);block=text[date.end():end]
        matches=list(pattern.finditer(block))
        if len(matches)!=len(re.findall(r'\b\d{2}:\d{2}\b',block)):raise ValueError('unparsed schedule clock')
        for match in matches:
            h,m=map(int,match['time'].split(':'))
            local=datetime(year,MONTH[date[3]],int(date[2]),h,m,tzinfo=ZoneInfo('Europe/London'))
            if local.strftime('%A')!=date[1] or local.tzname()!=zone:raise ValueError('date weekday or timezone conflict')
            start=date.end()+match.start();stop=date.end()+match.end()
            rows.append(dict(home=match['home'],away=match['away'],team_h=teams[match['home']],team_a=teams[match['away']],
                kickoff_time=local.astimezone(timezone.utc).isoformat(),local_date=local.date().isoformat(),local_time=match['time'],
                stated_zone=zone,condition_marker=match['condition'],conditional_as_printed=bool(match['condition']),
                source_start=start,source_end=stop,source_fragment_sha256=digest(text[start:stop].encode()),
                date_start=date.start(),date_end=date.end(),date_fragment_sha256=digest(date[0].encode()),
                available_at=None,eligible_predeadline=False))
    return rows


def build(base,root,out):
    mbytes=(root/'manifest.json').read_bytes();manifest=json.loads(mbytes)
    sources={r['article_id']:r for r in manifest['records']}
    if set(sources)!={a[0] for a in ARTICLES} or len(sources)!=len(manifest['records']):raise ValueError('source population differs')
    gate=json.loads((Path(__file__).parent/'results-g81.json').read_text())
    prior=base/'calendar-staleness-v1';report=json.loads(checked(prior/'report.json',gate['audit_report_sha256']))
    older=json.loads(checked(prior/'older_observed_calendars.json',report['artifacts']['older_observed_calendars.json']))
    diagnostic=json.loads(checked(prior/'later_reference_diagnostics.json',report['artifacts']['later_reference_diagnostics.json']))
    metadata=json.loads((base/'raw-history-v1/manifest.json').read_text());teams={}
    for season,sha in TEAM_SHA.items():
        records=[r for r in metadata['records'] if r['repository']=='vaastav/Fantasy-Premier-League' and r['path']=='data/'+season+'/teams.csv']
        if len(records)!=1 or records[0]['sha256']!=sha:raise ValueError('team metadata reference differs')
        rows=list(csv.DictReader(io.StringIO(checked(base/'raw-history-v1/objects'/sha,sha).decode())))
        teams[season]={r['name']:int(r['id']) for r in rows}
        if len(teams[season])!=20 or len(set(teams[season].values()))!=20:raise ValueError('club population differs')
    claims=[];comparisons=[];article_summary=[]
    for ident,season,year,date,date_iso,zone,title in ARTICLES:
        record=sources[ident]
        if record['url']!='https://www.premierleague.com/en/news/'+ident:raise ValueError('source URL differs')
        data=checked(root/'objects'/record['sha256'],record['sha256'])
        if len(data)!=record['bytes']:raise ValueError('source size differs')
        text=visible(data)
        if title not in text or date not in text:raise ValueError('article identity/date differs')
        parsed=schedule(text,year,zone,teams[season]) if zone else []
        for r in parsed:claims.append(dict(article_id=ident,season=season,displayed_date=date_iso,source_sha256=record['sha256'],**r))
        article_summary.append(dict(article_id=ident,displayed_date=date_iso,source_sha256=record['sha256'],bytes=record['bytes'],
            parsed_schedule_rows=len(parsed),conditional_rows=sum(r['conditional_as_printed'] for r in parsed),
            classification='schedule_statement' if zone else 'documentary_context_only'))
        for o,d in zip(older,diagnostic):
            if (o['season'],o['gw'])!=(d['season'],d['gw']):raise ValueError('parent pair mismatch')
            if o['season']!=season or date_iso>=o['deadline'][:10]:continue
            before=o['older_calendar'];after=json.loads(gzip.decompress(checked(base/'fixture-history-audit-v1/objects'/d['later_unproven_sha256'],d['later_unproven_sha256'])))
            index={ (f['team_h'],f['team_a']):f for f in before};after_by_id={f['id']:f for f in after}
            if len(index)!=380 or len(after_by_id)!=380:raise ValueError('fixture identity population differs')
            for claim in parsed:
                f=index[claim['team_h'],claim['team_a']];later=after_by_id[f['id']]
                if (later['team_h'],later['team_a'])!=(f['team_h'],f['team_a']):raise ValueError('fixture clubs differ')
                comparisons.append(dict(article_id=ident,season=season,gw=o['gw'],fixture=f['id'],
                    article_kickoff=claim['kickoff_time'],older_kickoff=f['kickoff_time'],later_unproven_kickoff=later['kickoff_time'],
                    equals_older=claim['kickoff_time']==f['kickoff_time'],equals_later=claim['kickoff_time']==later['kickoff_time'],
                    conditional_as_printed=claim['conditional_as_printed'],eligible_predeadline=False))
    out.mkdir(parents=True,exist_ok=True);artifacts={}
    for name,rows in [('schedule_claims.json',claims),('comparisons.json',comparisons)]:
        payload=(json.dumps(rows,indent=2)+'\n').encode();(out/name).write_bytes(payload);artifacts[name]=digest(payload)
    result=dict(version='fixture-announcement-evidence-v1',manifest_sha256=digest(mbytes),parent_report_sha256=gate['audit_report_sha256'],
        implementation_sha256=digest(Path(__file__).read_bytes()),team_metadata_sha256=TEAM_SHA,articles=article_summary,
        raw_bytes=sum(r['bytes'] for r in sources.values()),schedule_claims=len(claims),comparisons=len(comparisons),
        comparison_status=dict(Counter(('conditional_' if r['conditional_as_printed'] else 'unconditional_')+
            ('same_as_both' if r['equals_older'] and r['equals_later'] else 'same_as_older' if r['equals_older'] else 'same_as_later' if r['equals_later'] else 'differs_from_both') for r in comparisons)),
        changed_kickoff_fields_matching_unconditional_statement=len({(r['season'],r['gw'],r['fixture']) for r in comparisons if not r['conditional_as_printed'] and r['equals_later'] and not r['equals_older']}),
        training_admitted=False,production_changed=False,new_FPL_labels=0,selected_calendar_coverage_unchanged='195/199',
        limitations=['current_article_with_old_displayed_date_does_not_prove_historical_content',
            'conditional_statements_remain_conditional_even_when_dates_match',
            'nominal_date_filter_is_not_publication_admission',
            'comparison_is_with_snapshot_versions_not_realized_outcomes',
            'documentary_context_articles_not_parsed_as_fixture_assertions'],artifacts=artifacts)
    (out/'report.json').write_text(json.dumps(result,indent=2)+'\n');return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('base-root','root','out'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.base_root,a.root,a.out),indent=2))


if __name__=='__main__':main()
