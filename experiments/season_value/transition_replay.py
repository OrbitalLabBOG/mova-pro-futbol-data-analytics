"""EXP022 paired policy replay, admitted only after the mechanism screen."""
import argparse
import hashlib
import json
import time
from dataclasses import asdict
from pathlib import Path

import joblib
import pandas as pd

from experiments.long_horizon.metrics import paired_policy_bootstrap, paired_policy_influence
from experiments.long_horizon.projection import FixtureProjector
from experiments.long_horizon.season_boundary import BoundaryStore
from experiments.season_value.transition_planner import MarkovSeasonValue
from mova_fpl.engine.runner import Config
from mova_fpl.engine.season_value import SeasonValueModel, plan_season_value
from mova_fpl.engine.simulator import replay
from mova_fpl.trace import TraceWriter


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def immutable(path, payload):
    if path.exists():
        if json.loads(path.read_text()) != payload:
            raise ValueError(f'immutable conflict: {path.name}')
    else:
        path.write_text(json.dumps(payload, indent=2) + '\n')


class PairedProjector(FixtureProjector):
    """Planner-only arms must receive identical forecasts at every deadline."""
    def __init__(self, expected=None):
        super().__init__()
        self.expected = expected
        self.hashes = {}

    def __call__(self, **kwargs):
        bundle = super().__call__(**kwargs)
        payload = {'xp': bundle.xp.tolist(), 'horizon_xp': bundle.horizon_xp,
                   'horizon_sd': bundle.horizon_sd}
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True,
                                               allow_nan=False).encode()).hexdigest()
        key = str(kwargs['gw'])
        if self.expected is not None and self.expected.get(key) != fingerprint:
            raise ValueError(f'paired forecast mismatch before decision GW{key}')
        self.hashes[key] = fingerprint
        return bundle


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--parent', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--fpl-db', type=Path, required=True)
    p.add_argument('--freeze-only', action='store_true')
    args = p.parse_args()
    screen = json.loads((args.output / 'mechanism-evaluation.json').read_text())
    if not screen['mechanism_gate_passed']:
        raise ValueError('mechanism rejected; no policy replay')
    parent_manifest = json.loads((args.parent / 'manifest.json').read_text())
    if digest(args.fpl_db) != parent_manifest['dataset_sha256']:
        raise ValueError('parent dataset mismatch')
    model_path = args.parent / 'models/2025-26-baseline.joblib'
    sources = [Path(__file__), Path(__file__).with_name('transition.py'),
               Path(__file__).with_name('transition_planner.py')]
    inputs = [model_path] + sorted(args.parent.glob('*-opportunities.json'))
    spec = {'schema': 'mova-exp022-policy-protocol-v1', 'season': '2025-26',
            'phase': 'external_diagnostic', 'pristine_holdout': False,
            'control': 'season_value', 'candidate': 'markov_season_value',
            'parameters': {'horizon': 3, 'top_k': 20, 'time_limit': 3, 'decay': .84, 'seed': 42},
            'dataset_sha256': digest(args.fpl_db),
            'sources': {f.name: digest(f) for f in sources},
            'inputs': {f.relative_to(args.parent).as_posix(): digest(f) for f in inputs},
            'mechanism_sha256': digest(args.output / 'mechanism-evaluation.json'),
            'screen_gate': 'PVA-38 > 0; no parameter retuning after opening results',
            'promotion_authorized': False,
            'promotion_blockers': ['single historical chip season', 'final reschedule calendar',
                                   'no prospective planner release evidence',
                                   'action-independent transition approximation']}
    immutable(args.output / 'policy-protocol.json', spec)
    if args.freeze_only:
        print('policy protocol frozen', flush=True)
        return
    rows = [r for f in sorted(args.parent.glob('*-opportunities.json'))
            for r in json.loads(f.read_text())]
    reports = []
    for variant, cls in [('season_value', SeasonValueModel), ('markov_season_value', MarkovSeasonValue)]:
        destination = args.output / f'2025-26-{variant}-replay.json'
        if destination.exists():
            report = json.loads(destination.read_text())
            if report['protocol_sha256'] != digest(args.output / 'policy-protocol.json'):
                raise ValueError('replay protocol drift')
            reports.append(report)
            continue
        trace_path = args.output / f'2025-26-{variant}-trace.db'
        if trace_path.exists():
            raise ValueError('partial trace exists; preserve it and use a new output directory')
        # PointsModel.prepare_history can fit DefCon in-place. Never share a
        # predictor object across sequential seasons or policy arms.
        bundle = joblib.load(model_path)
        if any(s >= '2025-26' for s in bundle['minutes'].metadata['temporadas']):
            raise ValueError('future predictor training')
        projector = PairedProjector(reports[0]['projection_hashes'] if reports else None)
        planner = cls().fit(rows, target_season='2025-26')
        cfg = Config(policy='milp', projector='points', chip_policy='planner', **spec['parameters'])
        started = time.monotonic()
        result = replay('2025-26', config=cfg, store=BoundaryStore(args.fpl_db, 'append_full'),
                        trace=TraceWriter(trace_path), run_id=f'exp022-{variant}',
                        model_bundle=bundle, projection_fn=projector,
                        planner_fn=lambda s, x, o, c: plan_season_value(s, x, o, planner), verbose=True)
        report = {**asdict(result), 'total': result.total, 'variant': variant,
                  'projection_hashes': projector.hashes,
                  'wall_seconds': time.monotonic() - started,
                  'protocol_sha256': digest(args.output / 'policy-protocol.json')}
        if sorted(r['gw'] for r in report['gameweeks']) != list(range(1, 39)):
            raise ValueError('incomplete season')
        immutable(destination, report)
        reports.append(report)
        print(variant, result.total, flush=True)
    a, b = [pd.DataFrame(r['gameweeks']).assign(season='2025-26') for r in reports]
    delta = reports[1]['total'] - reports[0]['total']
    immutable(args.output / 'policy-evaluation.json', {
        'schema': 'mova-exp022-policy-evaluation-v1', 'pva_38': delta,
        'control_points': reports[0]['total'], 'candidate_points': reports[1]['total'],
        'paired_bootstrap': paired_policy_bootstrap(a, b),
        'influence': paired_policy_influence(a, b),
        'screen_passed': delta > 0, 'promotion_authorized': False,
        'promotion_blockers': spec['promotion_blockers']})


if __name__ == '__main__':
    main()
