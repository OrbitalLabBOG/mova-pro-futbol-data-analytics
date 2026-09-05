"""Publish sealed benchmark evidence to MLflow; never select a production model."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def sha(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def plan(snapshot):
    if snapshot.get('schema') != 'mova-internal-benchmark-v1' or snapshot.get('promotion_authorized') is not False:
        raise ValueError('only non-executable benchmark snapshots are accepted')
    runs = []
    def add(experiment, name, tags, metrics, evidence, model_name=None):
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
               for v in metrics.values()):
            raise ValueError('metrics must be finite numbers')
        tags = {**tags, 'benchmark_version': snapshot['benchmark_version'],
                'evidence_origin': 'historical_import', 'promotion_authorized': 'false'}
        identity = sha({'experiment': experiment, 'name': name, 'tags': tags,
                        'metrics': metrics, 'evidence': evidence})
        runs.append(dict(identity=identity, experiment=experiment, name=name, tags=tags,
                         metrics=metrics, evidence=evidence, model_name=model_name))
    for group in snapshot['groups']:
        experiment = 'mova/policy/' + group['id']
        tags = {k: group[k] for k in ['phase', 'comparison_sha256', 'control']}
        tags['source_experiment'] = group['experiment']
        for row in group['rows']:
            evidence = {'group': {k: v for k, v in group.items() if k != 'rows'}, 'result': row}
            metrics = {'mean_pva_38': row['mean_pva_38'], 'season_wins': row['wins'],
                       'season_losses': row['losses'], 'season_count': len(row['seasons'])}
            if row['uncertainty'] and row['uncertainty']['ci95'] is not None:
                metrics.update(ci95_low=row['uncertainty']['ci95'][0], ci95_high=row['uncertainty']['ci95'][1])
            model = 'mova.policy.' + re.sub(r'[^a-zA-Z0-9_.-]', '_', row['variant'])
            add(experiment, row['variant'] + '/summary', {**tags, 'variant': row['variant'], 'aggregation': 'summary'}, metrics, evidence, model)
            for season in row['seasons']:
                add(experiment, row['variant'] + '/' + season,
                    {**tags, 'variant': row['variant'], 'season': season, 'aggregation': 'season'},
                    {'net_points': row['candidate_points'][season], 'control_net_points': row['control_points'][season],
                     'pva_38': row['pva_38_by_season'][season]}, evidence)
    for panel in snapshot['predictive_panels']:
        for row in panel['values']:
            add('mova/prediction/' + panel['id'], row['variant'],
                {'source_file': panel['file'], 'source_sha256': panel['evidence_sha256'],
                 'phase': 'historical_diagnostic', 'variant': row['variant']},
                row['metrics'], panel)
    # Catalog entries are observations, not successful executions of all historical IDs.
    for entry in snapshot['catalog']:
        add('mova/catalog', entry['experiment'], {'source_experiment': entry['experiment'],
            'original_completion_status': entry['completion_status'], 'aggregation': 'inventory'},
            {'metadata_file_count': len(entry['metadata_files'])}, entry)
    if len({r['identity'] for r in runs}) != len(runs):
        raise ValueError('duplicate planned evidence')
    return runs


def configure_credentials(path, role='writer'):
    if path:
        data = json.loads(Path(path).read_text())
        os.environ['MLFLOW_TRACKING_USERNAME'] = data[role + '_user']
        os.environ['MLFLOW_TRACKING_PASSWORD'] = data[role + '_password']


def get_experiment(client, name):
    experiment = client.get_experiment_by_name(name)
    if experiment:
        if experiment.lifecycle_stage != 'active':
            raise ValueError('experiment was deleted; restore explicitly')
        return experiment.experiment_id
    return client.create_experiment(name, tags={'owner': 'MOVA', 'promotion_authorized': 'false'})


def model_version(client, name, run_id, identity, source, kind):
    from mlflow.exceptions import MlflowException
    try:
        client.get_registered_model(name)
    except MlflowException as exc:
        if exc.error_code != 'RESOURCE_DOES_NOT_EXIST':
            raise
        client.create_registered_model(name, tags={'promotion_authorized': 'false', 'artifact_kind': kind})
    versions = list(client.search_model_versions(f"name = '{name}'"))
    matches = [v for v in versions if v.tags.get('evidence_identity') == identity]
    if len(matches) > 1:
        raise ValueError('duplicate model versions for evidence')
    if matches:
        return matches[0].version
    return client.create_model_version(name, source=source, run_id=run_id,
                                      tags={'evidence_identity': identity, 'artifact_kind': kind,
                                            'promotion_authorized': 'false'}).version


def sync(client, runs, actor, reason):
    result = {'created': 0, 'reused': 0, 'runs': [], 'promotion_authorized': False}
    for row in runs:
        experiment_id = get_experiment(client, row['experiment'])
        found = client.search_runs([experiment_id], filter_string=f"tags.evidence_identity = '{row['identity']}'")
        if len(found) > 1:
            raise ValueError('duplicate run identity; refusing to choose arbitrarily')
        if found:
            run = found[0]
            if run.info.status == 'FINISHED':
                if run.data.metrics != row['metrics']:
                    raise ValueError('finished run metrics drift')
                result['reused'] += 1
            else:
                # Resume incomplete imports under the serialized writer lock.
                client.update_run(run.info.run_id, status='RUNNING')
        else:
            run = client.create_run(experiment_id, run_name=row['name'], tags={**row['tags'],
                'evidence_identity': row['identity'], 'import_actor': actor, 'import_reason': reason,
                'timestamps_mean': 'import_time_not_original_execution'})
            result['created'] += 1
        run_id = run.info.run_id
        if run.info.status != 'FINISHED':
            for key, value in row['metrics'].items():
                client.log_metric(run_id, key, value)
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'evidence.json'
                path.write_text(canonical(row))
                client.log_artifact(run_id, str(path), 'evidence')
            client.set_terminated(run_id, status='FINISHED')
        version = None
        if row['model_name']:
            version = model_version(client, row['model_name'], run_id, row['identity'],
                                    f'runs:/{run_id}/evidence', 'policy_evidence_descriptor_not_serving_model')
        result['runs'].append({'identity': row['identity'], 'run_id': run_id, 'model_version': version})
    return result


def verify(client, runs):
    checked = 0
    with tempfile.TemporaryDirectory() as directory:
        for row in runs:
            experiment = client.get_experiment_by_name(row['experiment'])
            if experiment is None:
                raise ValueError('missing experiment')
            found = client.search_runs([experiment.experiment_id], filter_string=f"tags.evidence_identity = '{row['identity']}'")
            if len(found) != 1 or found[0].info.status != 'FINISHED' or found[0].data.metrics != row['metrics']:
                raise ValueError('missing, duplicate or altered run')
            run = found[0]
            for key, value in row['tags'].items():
                if run.data.tags.get(key) != str(value):
                    raise ValueError('run tags drift')
            path = client.download_artifacts(run.info.run_id, 'evidence/evidence.json', directory)
            if json.loads(Path(path).read_text()) != row:
                raise ValueError('artifact drift')
            checked += 1
    return {'verified_runs': checked, 'status': 'pass', 'promotion_authorized': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['plan', 'sync', 'verify', 'export'])
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--tracking-uri', default=os.environ.get('MLFLOW_TRACKING_URI'))
    parser.add_argument('--credentials', type=Path)
    parser.add_argument('--actor')
    parser.add_argument('--reason')
    parser.add_argument('--lock-file', type=Path, default=Path('/imports/tracking.lock'))
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    runs = plan(json.loads(args.snapshot.read_text()))
    if args.action == 'plan':
        print(json.dumps({'runs': len(runs), 'experiments': len({r['experiment'] for r in runs}),
                          'registry_descriptors': sum(r['model_name'] is not None for r in runs)}))
        return
    if args.action == 'export':
        if not args.output:
            parser.error('--output required')
        # Export explicit benchmark metrics/configuration only; no recursive raw-directory upload.
        with args.output.open('x') as f:
            json.dump({'schema': 'mova-mlops-publication-candidate-v1', 'publication_approved': False,
                       'snapshot_sha256': hashlib.sha256(args.snapshot.read_bytes()).hexdigest(),
                       'runs': runs}, f, indent=2, allow_nan=False)
        return
    if not args.tracking_uri:
        parser.error('--tracking-uri required')
    configure_credentials(args.credentials)
    from mlflow import MlflowClient
    client = MlflowClient(tracking_uri=args.tracking_uri)
    if args.action == 'verify':
        print(json.dumps(verify(client, runs)))
        return
    if not args.actor or not args.reason:
        parser.error('--actor and --reason required for sync')
    args.lock_file.parent.mkdir(parents=True, exist_ok=True)
    with args.lock_file.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        result = sync(client, runs, args.actor, args.reason)
    if args.output:
        args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'runs'}))


if __name__ == '__main__':
    main()
