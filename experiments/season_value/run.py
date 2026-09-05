"""EXP-MOVA-2026-021: frozen participation and joint chip-value challengers.

Historical chip opportunities are hypothetical training observations, not claims
of legal historical chip replay. Full chip-policy comparison uses 2025-26 only.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from experiments.long_horizon.run import CachedStore, _write_json, _sha256, _source_sha
from experiments.long_horizon.models import fit_temporal_fold
from experiments.long_horizon.season_boundary import BoundaryStore, boundary_history, predictive_metrics
from experiments.long_horizon.projection import FixtureProjector
from mova_fpl.engine.projection import _proba_minutos
from mova_fpl.models.participation import ParticipationModel
from mova_fpl.engine.runner import Config
from mova_fpl.engine.simulator import replay
from mova_fpl.engine.planner import structure_factor
from mova_fpl.engine.policies import optimizer_config
from mova_fpl.engine.season_value import SeasonValueModel, opportunity_values, plan_season_value, CHIPS
from mova_fpl.rules import get as get_rules
from mova_fpl.trace import TraceWriter

ROOT = Path(__file__).resolve().parents[2]
DEFAULT = ROOT.parent / 'mova-fpl-experiments' / 'EXP-MOVA-2026-021'
SEASONS = ('2021-22', '2023-24', '2024-25', '2025-26')


def manifest(args):
    out = Path(args.output)
    payload = {'experiment_id': 'EXP-MOVA-2026-021',
        'dataset_sha256': _sha256(Path(args.fpl_db)),
        'hypothesis': 'recent participation context improves decisions; joint inventory values improve chip timing',
        'development': list(SEASONS[:-1]), 'external_diagnostic': SEASONS[-1],
        'external_is_pristine_holdout': False,
        'fixed_parameters': {'history': 'append_full', 'horizon': 3, 'decay': .84,
                             'top_k': 20, 'solver_seconds': 3, 'seed': 42},
        'gate': {'predictive': 'lower mean log loss and p60 Brier; improves >=2/3 development seasons',
                 'policy': 'positive mean net season points and >=2/3 development wins',
                 'production': 'existing multi-GW release gate; historical research cannot replace it'},
        'limitations': ['final historical reschedule calendar', 'historical chips unsupported before 2025-26',
                        'opportunity training on hypothetical chip deltas, no synthetic efficacy results',
                        'CBC fixed 3s budget, solutions need not be proven optimal']}
    path = out/'manifest.json'
    if path.exists() and json.loads(path.read_text()) != payload:
        raise ValueError('manifest conflict; use a new experiment directory')
    _write_json(path, payload)
    return out


def bundles(store, season, out):
    basepath = out/'models'/f'{season}-baseline.joblib'
    candpath = out/'models'/f'{season}-participation.joblib'
    source = hashlib.sha256((ROOT/'mova_fpl/models/participation.py').read_bytes()).hexdigest()
    if not basepath.exists():
        cached = ROOT.parent/'mova-fpl-experiments'/'EXP-MOVA-2026-003'/'artifacts'/f'fold-{season}.joblib'
        if cached.exists():
            base = joblib.load(cached)
        else:
            past = store.multi_season_as_of(season, 1)
            base = fit_temporal_fold(past, season)
        basepath.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(base, basepath)
    base = joblib.load(basepath)
    if any(s >= season for s in base['minutes'].metadata['temporadas']):
        raise ValueError('baseline future training')
    if candpath.exists():
        candidate = joblib.load(candpath)
        if candidate['metadata']['participation_source_sha256'] != source:
            raise ValueError('candidate source drift')
    else:
        past = store.multi_season_as_of(season, 1)
        calibration = max(past['season'].astype(str))
        candidate = copy.deepcopy(base)
        candidate['minutes'] = ParticipationModel().fit(past, calib_season=calibration)
        candidate['metadata'] = {**candidate.get('metadata',{}), 'participation_source_sha256': source}
        joblib.dump(candidate, candpath)
    return base, candidate


def predict(args, out):
    store = CachedStore(args.fpl_db)
    for season in SEASONS:
        dest=out/f'{season}-predictive.json'
        if dest.exists():
            continue
        print('fit/predict', season, flush=True)
        base, candidate = bundles(store, season, out)
        records=[]
        for gw in range(1,39):
            roster=store.roster(season,gw).drop_duplicates('element').reset_index(drop=True)
            if roster.empty: continue
            history=boundary_history(store,season,gw,'append_full')
            current=history[history['season'].eq(season)]
            # Single-fixture rows avoid calling an aggregated DGW label a per-fixture prediction.
            results=store.results(season,gw)
            counts=results.groupby('element').size()
            roster=roster[roster['element'].map(counts).eq(1)].reset_index(drop=True)
            actual=results.groupby('element')['minutes'].sum()
            minutes=roster['element'].map(actual).to_numpy()
            y=np.select([minutes<=0,minutes<60],[0,1],default=2)
            bp=_proba_minutos(history,roster,base['minutes'])
            cp=_proba_minutos(history,roster,candidate['minutes'])
            resetp=_proba_minutos(current if not current.empty else history,roster,base['minutes'])
            n=current.groupby('player_key').size()
            for variant,p in [('baseline',bp),('participation',cp),('ensemble50',.5*(bp+resetp))]:
                frame=pd.DataFrame({'season':season,'gw':gw,'element':roster['element'],
                    'variant':variant,'actual_class':y,'p0':p[:,0],'p1':p[:,1],'p60':p[:,2],
                    'low_current_history':roster['player_key'].map(n).fillna(0).lt(4).to_numpy()})
                records.append(frame)
            if gw%10==0: print('predict',season,gw,flush=True)
        rows=pd.concat(records,ignore_index=True)
        rows.to_csv(out/f'{season}-predictions.csv.gz',index=False)
        metrics=[]
        for variant,frame in rows.groupby('variant'):
            metrics.append({'variant':variant,**predictive_metrics(frame),
                'low_current_history':predictive_metrics(frame[frame['low_current_history']])})
        result={'season':season,'metrics':metrics,'model_sha256':_sha256(out/'models'/f'{season}-participation.joblib')}
        _write_json(dest,result);print(json.dumps(result),flush=True)


def run_policy(args,out):
    season=args.season; variant=args.variant
    store=BoundaryStore(args.fpl_db,'append_full')
    base,candidate=bundles(CachedStore(args.fpl_db),season,out)
    model=candidate if variant in ('participation','combined') else base
    chips=season=='2025-26'
    cfg=Config(policy='milp',projector='points',horizon=3,top_k=20,time_limit=3,
               chip_policy='planner' if chips else 'none')
    observations=[]
    def collect(state):
        if args.collect_opportunities:
            # Pure observation on the current legal baseline state. No chip is applied.
            hypothetical=replace(state,chips=get_rules('2026-27').CHIPS,chips_used=())
            values,_=opportunity_values(hypothetical,state.horizon_xp,optimizer_config(cfg,3),replenish=True)
            if all(c in values for c in CHIPS):
                observations.append({'season':season,'gw':state.gw,'values':values,
                    'structure':{c:structure_factor(c,state.gw,state.schedule) for c in CHIPS}})
            _write_json(out/f'{season}-opportunities.json',observations)
        return None
    sv=None
    if variant in ('season_value','combined'):
        training=[]
        for p in sorted(out.glob('*-opportunities.json')):
            training.extend(r for r in json.loads(p.read_text()) if r['season']<season)
        sv=SeasonValueModel().fit(training,target_season=season)
        joblib.dump(sv,out/'models'/f'{season}-season-value.joblib')
    result=replay(season,config=cfg,store=store,
        trace=TraceWriter(out/f'{season}-{variant}-trace.db'),
        run_id=f'exp021-{season}-{variant}',model_bundle=model,
        projection_fn=None if variant=='runtime_matrix' else FixtureProjector(),
        planner_fn=(lambda s,x,o,c:plan_season_value(s,x,o,sv)) if sv else None,
        agent_fn=collect if args.collect_opportunities else None,verbose=True)
    payload={**asdict(result),'total':result.total,'config':asdict(cfg),
             'source_sha256':_source_sha(ROOT),'variant':variant,
             'baseline_model_sha256':_sha256(out/'models'/f'{season}-baseline.joblib'),
             'candidate_model_sha256':_sha256(out/'models'/f'{season}-participation.joblib')}
    _write_json(out/f'{season}-{variant}-replay.json',payload)
    print(json.dumps({'season':season,'variant':variant,'total':result.total,'wasted':result.wasted_chips}),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase',choices=['predict','replay'])
    p.add_argument('--fpl-db',required=True);p.add_argument('--output',default=str(DEFAULT))
    p.add_argument('--season',choices=SEASONS,default='2025-26')
    p.add_argument('--variant',choices=['baseline','runtime_matrix','participation','season_value','combined'],default='baseline')
    p.add_argument('--collect-opportunities',action='store_true')
    a=p.parse_args();out=manifest(a)
    if a.phase=='predict':predict(a,out)
    else:run_policy(a,out)

if __name__=='__main__':main()
