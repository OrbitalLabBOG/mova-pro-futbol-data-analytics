#!/usr/bin/env bash
set -euo pipefail
umask 077
actor=${1:?actor required}
reason=${2:?reason required}
exec 9>/var/lib/mova-mlflow/imports/tracking.lock
flock -x 9
backup_dir=/opt/orbital/backups/mova-mlflow/$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$backup_dir"
chmod 700 "$backup_dir"
resume() { /usr/local/bin/mova-mlflow start tracking >/dev/null; }
trap resume EXIT
/usr/local/bin/mova-mlflow stop tracking >/dev/null
/usr/local/bin/mova-mlflow exec -T postgres pg_dump -U mlflow -Fc mlflow > "$backup_dir/tracking.dump"
/usr/local/bin/mova-mlflow exec -T postgres pg_dump -U mlflow -Fc mlflow_auth > "$backup_dir/auth.dump"
tar -czf "$backup_dir/artifacts.tar.gz" -C /var/lib/mova-mlflow artifacts imports
tar -czf "$backup_dir/config.tar.gz" -C /etc mova-mlflow
/usr/local/bin/mova-mlflow exec -T postgres psql -U mlflow -d mlflow -Atc 'SELECT count(*) FROM runs' > "$backup_dir/run-count.txt"
python3 - "$backup_dir" "$actor" "$reason" <<'PY'
import json,sys
from pathlib import Path
root=Path(sys.argv[1])
(root/'audit.json').write_text(json.dumps({'actor':sys.argv[2],'reason':sys.argv[3],
 'idempotency_key':'mlflow-backup:'+root.name,'scope':'mlflow_only'},indent=2))
PY
(cd "$backup_dir" && sha256sum tracking.dump auth.dump artifacts.tar.gz config.tar.gz run-count.txt audit.json > SHA256SUMS)
resume
trap - EXIT
/usr/local/bin/mova-mlflow up -d --wait tracking >/dev/null
printf '%s\n' "$backup_dir"
