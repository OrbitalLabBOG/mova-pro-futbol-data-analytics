"""Start authenticated tracking without credentials in command arguments."""
import json
import os
from pathlib import Path

secrets = Path('/run/secrets/mlflow')
config = json.loads((secrets / 'credentials.json').read_text())
os.environ['MLFLOW_SERVER_ENABLE_JOB_EXECUTION'] = 'false'
os.environ['MLFLOW_BACKEND_STORE_URI'] = config['database_uri']
os.environ['MLFLOW_AUTH_CONFIG_PATH'] = str(secrets / 'auth.ini')
os.environ['MLFLOW_FLASK_SERVER_SECRET_KEY'] = config['csrf_key']
os.execvp('mlflow', ['mlflow', 'server', '--app-name', 'basic-auth',
                    '--host', '0.0.0.0', '--port', '5000', '--workers', '1',
                    '--artifacts-destination', '/mlartifacts',
                    '--allowed-hosts', 'mlflow.72-60-245-2.sslip.io,127.0.0.1:*,localhost:*'])
