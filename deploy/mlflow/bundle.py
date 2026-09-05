"""Archive the sealed shadow model bundle without loading pickles or activating it."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys

from mlflow import MlflowClient
from experiments.benchmark.tracking import configure_credentials, get_experiment, model_version

lock = open('/imports/tracking.lock', 'a')
fcntl.flock(lock, fcntl.LOCK_EX)
configure_credentials('/run/secrets/mlflow/credentials.json')
client = MlflowClient(tracking_uri='http://127.0.0.1:5000')
root = Path('/imports/model-bundle')
manifest_path = root / 'season-value-1.0.0.json'
manifest = json.loads(manifest_path.read_text())
if manifest['selected_for_execution'] is not False:
    raise ValueError('manifest is executable')
files = []
metadata = {}
for family in ['minutes', 'points']:
    for meta_path in sorted((root / 'models' / family).glob(f'{family}-*.json')):
        meta = json.loads(meta_path.read_text())
        version = meta['version']
        path = meta_path.with_suffix('.joblib')
        observed = hashlib.sha256(path.read_bytes()).hexdigest()
        files.append((family, version, path, meta.get('artifact_sha256', observed)))
        meta['archive_digest_source'] = 'historical_metadata' if 'artifact_sha256' in meta else 'computed_at_archive'
        meta['archive_observed_sha256'] = observed
        metadata[(family, version)] = {k: v for k, v in meta.items() if k != 'artifact'}
    expected = manifest['models'][family]
    if not any(f == family and v == expected['version'] and h == expected['artifact_sha256']
               for f, v, p, h in files):
        raise ValueError('sealed model missing from archive')
files.append(('season_value', manifest['season_value']['version'], manifest_path,
              hashlib.sha256(manifest_path.read_bytes()).hexdigest()))
for family, version, path, expected in files:
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError('model hash mismatch: ' + family)
exp = get_experiment(client, 'mova/model-artifacts')
output = []
for family, version, path, identity in files:
    found = client.search_runs([exp], filter_string=f"tags.evidence_identity = '{identity}'")
    if len(found) > 1:
        raise ValueError('duplicate model archive')
    run = found[0] if found else client.create_run(exp, run_name=family + '/' + version,
        tags={'evidence_identity': identity, 'semantic_version': version,
              'artifact_kind': 'joblib' if family != 'season_value' else 'strategy_manifest',
              'promotion_authorized': 'false', 'evidence_origin': 'verified_artifact_archive',
              'digest_provenance': metadata.get((family,version),{}).get('archive_digest_source','sealed_manifest'),
              'original_git_sha': metadata.get((family,version),{}).get('git_sha','not_recorded'),
              'original_trained_at': metadata.get((family,version),{}).get('trained_at','not_recorded'),
              'import_actor': os.environ.get('MOVA_IMPORT_ACTOR', 'codex'),
              'import_reason': 'Archive exact sealed analytical shadow bundle'})
    if run.info.status != 'FINISHED':
        client.log_artifact(run.info.run_id, str(path), 'model')
        if (family, version) in metadata:
            meta_file = Path('/tmp') / f'{family}-{version}-metadata.json'
            meta_file.write_text(json.dumps(metadata[family, version], indent=2))
            client.log_artifact(run.info.run_id, str(meta_file), 'model')
        client.set_terminated(run.info.run_id, status='FINISHED')
    mv = model_version(client, 'mova.' + family, run.info.run_id, identity,
                       f'runs:/{run.info.run_id}/model', 'raw_artifact_not_mlflow_serving_flavor')
    downloaded = client.download_artifacts(run.info.run_id, 'model/' + path.name, '/tmp/bundle-verify')
    if hashlib.sha256(Path(downloaded).read_bytes()).hexdigest() != identity:
        raise ValueError('archive roundtrip hash mismatch')
    output.append({'family': family, 'semantic_version': version, 'mlflow_version': mv,
                   'run_id': run.info.run_id, 'sha256': identity})
print(json.dumps({'status': 'pass', 'models': output, 'promotion_authorized': False}))
