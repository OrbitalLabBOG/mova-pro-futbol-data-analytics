"""Reconcile combined labels against individual FPL history and season metadata."""
from __future__ import annotations

import pandas as pd


def repair_player(frame: pd.DataFrame,individual: pd.DataFrame,metadata: pd.DataFrame,components: list[str]):
    keys=['element','fixture'];columns=['minutes','total_points']+components
    if individual.element.nunique()!=1 or individual.duplicated(keys).any():raise ValueError('ambiguous individual player history')
    element=int(individual.iloc[0].element);meta=metadata[metadata.id.eq(element)]
    if len(meta)!=1:raise ValueError('missing unique player metadata')
    meta=meta.iloc[0];old=frame[frame.element.eq(element)]
    if old.empty or not old.official_player_code.eq(meta.code).all():raise ValueError('player code disagreement')
    joined=old.merge(individual,on=keys,how='outer',suffixes=('_old','_new'),indicator=True,validate='one_to_one')
    if joined['_merge'].ne('both').any():raise ValueError('individual fixture coverage mismatch')
    if joined.gw.ne(joined['round_new']).any():raise ValueError('individual gameweek disagreement')
    if not pd.to_datetime(joined.kickoff_time_old,utc=True).eq(pd.to_datetime(joined.kickoff_time_new,utc=True)).all():
        raise ValueError('individual kickoff disagreement')
    for column in columns:
        values=pd.to_numeric(individual[column],errors='raise')
        if values.isna().any() or not values.mod(1).eq(0).all():raise ValueError('invalid individual outcome')
        if column not in meta or values.sum()!=meta[column]:raise ValueError('individual season total disagreement')
    if not individual.minutes.between(0,90).all():raise ValueError('invalid individual minutes')
    result=frame.copy();changes=[]
    for row in joined.to_dict('records'):
        index=result.index[result.element.eq(element)&result.fixture.eq(row['fixture'])]
        if len(index)!=1:raise ValueError('ambiguous target label')
        for column in columns:
            before=row[column+'_old'];after=row[column+'_new']
            if before!=after:
                result.loc[index,column]=after
                changes.append(dict(element=element,official_player_code=int(meta.code),fixture=int(row['fixture']),
                    field=column,before=int(before),after=int(after)))
    return result,changes
