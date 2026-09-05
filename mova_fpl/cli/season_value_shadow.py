"""Harness adapter for a sealed, non-executable analytical policy challenger."""
from __future__ import annotations
import hashlib
import json
import re
from dataclasses import replace
from pathlib import Path
from mova_fpl.data import live
from mova_fpl.engine.projection import fixture_horizon_projection
from mova_fpl.engine.planner import plan, PlannerConfig, ChipVerdict
from mova_fpl.engine.policies import optimizer_config
from mova_fpl.engine.runner import decide
from mova_fpl.engine.season_value import SeasonValueModel, plan_season_value
from mova_fpl.engine.virtual_shadow import restore_virtual_state, next_virtual_state
from mova_fpl.models import registry


def load_manifest(path, expected_sha):
    if not path or not expected_sha or not re.fullmatch(r'[0-9a-f]{64}', expected_sha):
        raise ValueError('season-value shadow requires manifest and SHA-256')
    raw=Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected_sha:
        raise ValueError('season-value manifest hash mismatch')
    payload=json.loads(raw)
    if payload.get('schema')!='mova-season-value-shadow-v1' or payload.get('selected_for_execution') is not False:
        raise ValueError('invalid shadow authority/schema')
    models={}
    for family in ('minutes','points'):
        spec=payload['models'][family]
        version=spec['version']
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,80}',version):
            raise ValueError('invalid model version')
        artifact=registry.ARTIFACTS/family/f'{family}-{version}.joblib'
        if hashlib.sha256(artifact.read_bytes()).hexdigest()!=spec['artifact_sha256']:
            raise ValueError('shadow model artifact hash mismatch')
        models[family]=registry.load(family,version)
    spec=payload['season_value']
    model=SeasonValueModel(version=spec['version']).fit(spec['samples'],target_season=payload['season'])
    return payload,models,model


def build_shadow(*,season,gw,cfg,fx,boot,base_state,history,roster,models,
                 manifest_path,manifest_sha256,prior_path=None,prior_sha256=None):
    from mova_fpl.cli.live import _candidate,_prior_virtual_states
    payload,challenger,chip_model=load_manifest(manifest_path,manifest_sha256)
    if payload['season']!=season:
        raise ValueError('shadow manifest season mismatch')
    for family in ('minutes','points'):
        if any(s>=season for s in challenger[family].metadata.get('temporadas',())):
            raise ValueError('shadow model future training')
    strategy='season_value_v2'
    variant=payload.get('variant', 'combined')
    if variant not in {'combined', 'season_value'}:
        raise ValueError('unknown policy variant')
    control_signature={name: str(models[name].version) for name in ('minutes', 'points')}
    previous,continuity=_prior_virtual_states(prior_path,prior_sha256,season=season,gw=gw,strategy_key=strategy)
    # A policy/bundle change starts a new sequence, never merges unlike evidence.
    if previous and prior_path:
        prior=json.loads(Path(prior_path).read_text())['strategy_shadow']
        if (prior.get('model_manifest_sha256')!=manifest_sha256
                or prior.get('control_model_signature')!=control_signature):
            previous=None
            continuity={'mode':'initialized_from_observed','reason':'candidate_manifest_changed'}
    config=replace(cfg,horizon=3,top_k=20,time_limit=3,chip_policy='planner')
    output={'schema':'mova-strategy-shadow-v1','experiment_id':'EXP-MOVA-2026-021',
        'strategy_key':strategy,'season':season,'gw':gw,'status':'shadow_only',
        'selected_for_execution':False,'virtual_trajectory':True,'trajectory':continuity,
        'horizon':3,'decay':config.decay,'chips':'joint_inventory_in_both_arms',
        'model_manifest_sha256':manifest_sha256,'variant':variant,
        'control_model_signature':control_signature,
        'controlled_variable':('learned chip opportunity value' if variant=='season_value'
                               else 'joint policy: participation plus learned chip opportunity value'),
        'information_set':'sealed current state; published fixture horizon; prior-season opportunity samples',
        'prior_chips_used':{},'next_state':{},'projections':{},'planner':{}}
    for arm,bundle in [('control',models),('candidate',challenger)]:
        state=base_state
        if previous:
            state=restore_virtual_state(previous[arm],base_state=state,boot=boot,
                expected_strategy=strategy,expected_arm=arm,expected_previous_gw=gw-1)
        if state.chips is None:
            raise ValueError('season-value shadow requires chip inventory')
        projection=fixture_horizon_projection(history=history,roster=roster,modelos=bundle,
            season=season,gw=gw,horizon=min(3,39-gw),decay=config.decay,
            schedule=live.fixture_schedule(fx,boot,gw,min(38,gw+2)),
            disponibilidad=roster['disponibilidad'].to_numpy())
        xp=projection.horizon_xp
        state=replace(state,chips_allowed={},horizon_xp=xp,horizon_sd=projection.horizon_sd,
            candidates=tuple(replace(c,xp=xp[gw].get(c.element,0.)) for c in state.candidates))
        ocfg=optimizer_config(config,len(xp))
        if state.is_cold_start:
            verdict=ChipVerdict(gw,None,0.,0.,'cold start')
        else:
            verdict=(plan(state,xp,ocfg,PlannerConfig(enabled=True)) if arm=='control'
                     else plan_season_value(state,xp,ocfg,chip_model))
        if verdict.chip:
            state=replace(state,chips_allowed={gw:frozenset({verdict.chip})})
        decision=decide(gw,state,config)
        output[arm]=_candidate(f'shadow_{strategy}_{arm}',arm,decision,state)
        output['planner'][arm]={'chip':verdict.chip,'value':verdict.value,'threshold':verdict.threshold,'reason':verdict.reason}
        output['prior_chips_used'][arm]=[{'gw':u.gw,'chip':u.chip} for u in state.chips_used]
        output['next_state'][arm]=next_virtual_state(decision,state=state,boot=boot,strategy_key=strategy,arm=arm)
        output['projections'][f'{arm}_horizon_xp']=xp
        if arm=='candidate':output['projections']['candidate_horizon_sd']=projection.horizon_sd
    a,b=output['control']['decision'],output['candidate']['decision']
    output['comparison']={'fingerprint_changed':a['fingerprint']!=b['fingerprint'],
        'current_gw_expected_points_delta':round(b['expected_points']-a['expected_points'],2),
        'control_hits':a['hits'],'candidate_hits':b['hits'],
        'control_transfers':len(a['transfers_in']),'candidate_transfers':len(b['transfers_in'])}
    return output
