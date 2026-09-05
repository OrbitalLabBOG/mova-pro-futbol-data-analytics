"""Initialize dedicated writer/reader roles through supported MLflow auth APIs."""
import fcntl
import json
import os
from pathlib import Path

os.environ['MLFLOW_DISABLE_AGENT_HINT'] = '1'
from mlflow.server.auth.client import AuthServiceClient
from mlflow.exceptions import MlflowException

lock = open('/imports/accounts.lock', 'a')
fcntl.flock(lock, fcntl.LOCK_EX)
config = json.loads(Path('/run/secrets/mlflow/credentials.json').read_text())
os.environ['MLFLOW_TRACKING_USERNAME'] = config['admin_user']
os.environ['MLFLOW_TRACKING_PASSWORD'] = config['admin_password']
client = AuthServiceClient('http://127.0.0.1:5000')
for kind, permission in [('writer', 'EDIT'), ('reader', 'READ')]:
    username = config[kind + '_user']
    try:
        client.get_user(username)
    except MlflowException as exc:
        if exc.error_code != 'RESOURCE_DOES_NOT_EXIST':
            raise
        client.create_user(username, config[kind + '_password'])
    roles = [r for r in client.list_roles('default') if r.name == 'mova-' + kind]
    role = roles[0] if roles else client.create_role('default', 'mova-' + kind, 'MOVA tracking ' + kind)
    existing = client.list_role_permissions(role.id)
    for resource in ['experiment', 'registered_model']:
        if not any(p.resource_type == resource and p.resource_pattern == '*' for p in existing):
            client.add_role_permission(role.id, resource, '*', permission)
    if not any(r.id == role.id for r in client.list_user_roles(username)):
        client.assign_role(username, role.id)
print('Writer and reader roles provisioned')
