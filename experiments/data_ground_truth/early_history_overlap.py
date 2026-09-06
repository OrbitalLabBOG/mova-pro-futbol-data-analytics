"""Measure complementary 2013/14 observations without merging source labels."""
from __future__ import annotations
import argparse
import io
import json
from pathlib import Path
import sqlite3
import pandas as pd
from experiments.data_ground_truth.differential_audit import read_tables
from experiments.data_ground_truth.historical_null_coverage import DATABASE_SHA
from experiments.data_ground_truth.identity_2014 import name_tokens
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked

FIXTURE_SHA='cae54cded8ed41bf60d44401f8f7626b8f3ac3bf3f107b4751cb5783653cb26a'


def compare(tables,teams,players,reference,labels,metadata):
    fixtures=tables['fixture'].loc[lambda x:x.season.eq(14)].copy()
    clubs=reference[['home_team','home_team_id']].drop_duplicates()
    if clubs.home_team.duplicated().any():raise ValueError('ambiguous club names')
    names=clubs.set_index('home_team').home_team_id
    mapping=teams.set_index('_id')['name'].replace({'Cardiff City':'Cardiff'}).map(names)
    fixtures['home_team_id']=fixtures.team_home_id.map(mapping)
    fixtures['away_team_id']=fixtures.team_away_id.map(mapping)
    keys=['home_team_id','away_team_id']
    if fixtures[keys].isna().any().any():raise ValueError('unknown fixture clubs')
    linked=fixtures.merge(reference[keys+['matchId','kickoff']],on=keys,how='outer',validate='one_to_one',indicator=True)
    if linked._merge.ne('both').any():raise ValueError('unmatched fixture clubs')
    dates=pd.to_datetime(linked.datetime,unit='s',utc=True).dt.tz_convert('Europe/London').dt.date
    if dates.ne(pd.to_datetime(linked.kickoff).dt.date).any():raise ValueError('fixture date conflict')
    old=tables['player_match'].loc[lambda x:x.season.eq(14),['player_player_id','fixture_id','gameweek','pl_team_id','opp_team_id','minutes','total']].copy()
    ids=tables['player_season'].loc[lambda x:x.season.eq(14),['player_id','fpl_id']]
    old=old.merge(ids,left_on='player_player_id',right_on='player_id',how='left',validate='many_to_one')
    if old.fpl_id.isna().any():raise ValueError('missing season player identity')
    old=old.merge(players,left_on='player_player_id',right_on='_id',how='left',validate='many_to_one').rename(columns={'name':'differential_name'})
    old=old.merge(linked[['_id','matchId']],left_on='fixture_id',right_on='_id',how='left',validate='many_to_one',suffixes=('','_fixture'))
    if old.matchId.isna().any() or old.differential_name.isna().any():raise ValueError('missing fixture or player name')
    old['differential_team_code']=old.pl_team_id.map(mapping)
    old['differential_opponent_code']=old.opp_team_id.map(mapping)
    new=labels[['id','matchId','gw','mins','gw_pts','match_team_code','opponent_code','official_player_code']].merge(metadata[['id','name']],on='id',how='left',validate='many_to_one')
    if new['name'].isna().any():raise ValueError('missing JSON player name')
    paired=old.merge(new,left_on=['fpl_id','matchId'],right_on=['id','matchId'],how='outer',validate='one_to_one',indicator=True)
    both=paired._merge.eq('both')
    paired['name_agrees']=[name_tokens(str(a))==name_tokens(str(b)) if ok else False for a,b,ok in zip(paired.differential_name,paired['name'],both)]
    paired['context_agrees']=both & paired.gameweek.eq(paired.gw) & paired.differential_team_code.eq(paired.match_team_code) & paired.differential_opponent_code.eq(paired.opponent_code)
    paired['corroborated_link']=paired.name_agrees & paired.context_agrees
    paired['minutes_conflict']=both & paired.minutes.notna() & paired.minutes.ne(paired.mins)
    paired['points_conflict']=both & paired.total.notna() & paired.total.ne(paired.gw_pts)
    paired['candidate_missing_points']=paired.corroborated_link & paired.total.isna() & ~paired.minutes_conflict
    paired['candidate_missing_minutes']=paired.corroborated_link & paired.minutes.isna() & ~paired.points_conflict
    paired['eligible_training']=False;paired['eligible_predeadline']=False
    report=dict(version='early-history-overlap-v1',fixture_links=len(linked),differential_rows=len(old),json_rows=len(new),
        paired_rows=int(both.sum()),json_only_rows=int(paired._merge.eq('right_only').sum()),
        differential_only_rows=int(paired._merge.eq('left_only').sum()),
        corroborated_rows=int(paired.corroborated_link.sum()),name_disagreements=int((both&~paired.name_agrees).sum()),
        context_disagreements=int((both&~paired.context_agrees).sum()),minutes_conflicts=int(paired.minutes_conflict.sum()),points_conflicts=int(paired.points_conflict.sum()),
        candidate_missing_points=int(paired.candidate_missing_points.sum()),candidate_missing_minutes=int(paired.candidate_missing_minutes.sum()),
        candidate_missing_points_players=int(paired.loc[paired.candidate_missing_points,'fpl_id'].nunique()),
        differential_positive_minutes_missing_points=int((paired.minutes.gt(0)&paired.total.isna()).sum()),
        positive_minutes_missing_points_not_recovered=int((paired.minutes.gt(0)&paired.total.isna()&~paired.candidate_missing_points).sum()),
        positive_minutes_missing_points_candidates=int((paired.candidate_missing_points&paired.minutes.gt(0)).sum()),
        json_only_positive_minutes=int((paired._merge.eq('right_only')&paired.mins.gt(0)).sum()),
        json_only_explicit_zero_minutes=int((paired._merge.eq('right_only')&paired.mins.eq(0)).sum()),
        new_complete_seasons=0,training_admitted=False,source_labels_modified=False,
        limitations=['same_season_fpl_id_with_name_and_fixture_context_not_global_identity',
                     'json_only_relative_to_selected_differential_database_not_all_archives',
                     'candidate_recoveries_not_applied_to_GT','no_predeadline_publication_proof'])
    paired=paired.rename(columns={'_merge':'source_presence'}).sort_values(['matchId','fpl_id','id'],na_position='last').reset_index(drop=True)
    return paired,report


def build(base,out):
    db=base/'raw-history-differential/objects'/DATABASE_SHA;checked(db,DATABASE_SHA)
    tables=read_tables(db)
    with sqlite3.connect(db.resolve().as_uri()+'?mode=ro&immutable=1',uri=True) as c:
        c.execute('PRAGMA trusted_schema=OFF');c.execute('PRAGMA query_only=ON')
        physical={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'team','player'}<=physical:raise ValueError('missing physical identity tables')
        teams=pd.read_sql_query('SELECT _id,name FROM team',c)
        players=pd.read_sql_query('SELECT _id,name FROM player',c)
    root=base/'early-json-audit-g88-v5'
    baseline=json.loads(Path(__file__).with_name('results-g88.json').read_text())
    report_raw=checked(root/'report.json',baseline['audit_report_sha256']);prior=json.loads(report_raw)
    def read(name):return pd.read_csv(io.BytesIO(checked(root/name,prior['artifacts'][name])))
    reference=pd.read_csv(io.BytesIO(checked(base/'raw-history-v2/objects'/FIXTURE_SHA,FIXTURE_SHA)))
    paired,report=compare(tables,teams,players,reference,read('2013-14-labels.csv'),read('2013-14-metadata.csv'))
    out.mkdir(parents=True,exist_ok=True)
    paired.to_csv(out/'observations.csv',index=False)
    report.update(database_sha256=DATABASE_SHA,fixture_sha256=FIXTURE_SHA,g88_report_sha256=digest(report_raw),
        implementation_sha256=digest(Path(__file__).read_bytes()),artifacts={'observations.csv':digest((out/'observations.csv').read_bytes())})
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.base,a.out),indent=2))
