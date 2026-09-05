"""Idempotent first-install credentials. Run as root on the VPS, never print values."""
import json
import os
from pathlib import Path
import secrets

root = Path('/etc/mova-mlflow')
root.mkdir(mode=0o750, exist_ok=True)
os.chown(root, 0, 10002)
path = root / 'credentials.json'
if not path.exists():
    password = secrets.token_hex(32)
    data = {'database_uri': f'postgresql+psycopg2://mlflow:{password}@postgres:5432/mlflow',
            'csrf_key': secrets.token_hex(32), 'admin_user': 'julian',
            'admin_password': secrets.token_urlsafe(32), 'writer_user': 'mova-writer',
            'writer_password': secrets.token_urlsafe(32), 'reader_user': 'mova-reader',
            'reader_password': secrets.token_urlsafe(32)}
    # Exclusive creation protects a rerun from changing credentials of an initialized DB.
    with path.open('x') as f:
        json.dump(data, f)
    (root / 'db_password').write_text(password)
    (root / 'auth.ini').write_text('[mlflow]\n' +
        'default_permission = NO_PERMISSIONS\nauth_cache_ttl_seconds = 5\n' +
        'database_uri = ' + data['database_uri'] + '_auth\n' +
        'admin_username = ' + data['admin_user'] + '\n' +
        'admin_password = ' + data['admin_password'] + '\n')
for name in ['credentials.json', 'db_password', 'auth.ini']:
    p = root / name
    os.chmod(p, 0o640)
    os.chown(p, 0, 10002)
for name in ['artifacts', 'imports']:
    p = Path('/var/lib/mova-mlflow') / name
    p.mkdir(parents=True, exist_ok=True)
    os.chown(p, 10002, 10002)
    os.chmod(p, 0o750)
print('MLflow credential files provisioned; values withheld')
