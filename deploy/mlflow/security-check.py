"""Exercise authentication and reader denial without changing FPL state."""
import json
from pathlib import Path
import requests

config = json.loads(Path('/run/secrets/mlflow/credentials.json').read_text())
base = 'http://127.0.0.1:5000'
session = requests.Session()
assert session.get(base + '/', timeout=15).status_code == 401
reader = (config['reader_user'], config['reader_password'])
writer = (config['writer_user'], config['writer_password'])
# MLflow 3.16 fail-closed UI route denies non-admins; API readers remain scoped.
admin = (config['admin_user'], config['admin_password'])
assert session.get(base + '/', auth=admin, timeout=15).status_code == 200
response = session.post(base + '/api/2.0/mlflow/experiments/search', auth=reader, json={'max_results': 100}, timeout=15)
response.raise_for_status()
experiments = response.json()['experiments']
assert experiments
exp_id = next(x['experiment_id'] for x in experiments if x['name'].startswith('mova/policy/'))
result = session.post(base + '/api/2.0/mlflow/runs/search', auth=reader,
                      json={'experiment_ids':[exp_id],'max_results':1},timeout=15)
result.raise_for_status()
run_id = result.json()['runs'][0]['info']['run_id']
response = session.post(base + '/api/2.0/mlflow/runs/set-tag', auth=reader,
                       json={'run_id':run_id,'key':'forbidden_reader_probe','value':'must_not_exist'},timeout=15)
assert response.status_code == 403, response.status_code
response = session.get(base + '/api/2.0/mlflow/runs/get', auth=writer, params={'run_id':run_id},timeout=15)
response.raise_for_status()
assert not any(t['key']=='forbidden_reader_probe' for t in response.json()['run']['data']['tags'])
assert session.get(base+'/',headers={'Host':'untrusted.invalid'},timeout=15).status_code == 403
print(json.dumps({'anonymous_denied':True,'admin_ui_access':True,'reader_api_can_read':True,'reader_write_denied':True,
                  'untrusted_host_denied':True,'status':'pass'}))
