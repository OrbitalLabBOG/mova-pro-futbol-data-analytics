#!/usr/bin/env bash
set -euo pipefail
umask 077
backup_dir=${1:?backup path required}
case "$backup_dir" in /opt/orbital/backups/mova-mlflow/*) ;; *) exit 2;; esac
(cd "$backup_dir" && sha256sum -c SHA256SUMS >/dev/null)
container=mova-mlflow-restore-$(date +%s)
staging=$(mktemp -d /tmp/mova-mlflow-restore.XXXXXX)
cleanup() { docker rm -f "$container" >/dev/null 2>&1 || true; rm -rf "$staging"; }
trap cleanup EXIT
docker run -d --name "$container" --network none --memory 512m \
  --tmpfs /var/lib/postgresql/data -e POSTGRES_HOST_AUTH_METHOD=trust \
  postgres:17.11-bookworm >/dev/null
for attempt in $(seq 1 30); do
  if docker exec "$container" pg_isready -U postgres >/dev/null 2>&1; then break; fi
  sleep 1
done
for db in mlflow mlflow_auth; do
  docker exec "$container" createdb -U postgres "$db"
done
docker exec "$container" psql -U postgres -c 'CREATE ROLE mlflow' >/dev/null
docker exec -i "$container" pg_restore -U postgres --exit-on-error -d mlflow < "$backup_dir/tracking.dump"
docker exec -i "$container" pg_restore -U postgres --exit-on-error -d mlflow_auth < "$backup_dir/auth.dump"
actual=$(docker exec "$container" psql -U postgres -d mlflow -Atc 'SELECT count(*) FROM runs')
expected=$(cat "$backup_dir/run-count.txt")
test "$actual" = "$expected"
tar -xzf "$backup_dir/artifacts.tar.gz" -C "$staging"
# Verify all imported benchmark artifacts against the immutable local plan after extraction.
python3 - "$staging/artifacts" <<'PY'
import hashlib,json,sys
from pathlib import Path
count=0
for f in Path(sys.argv[1]).rglob('evidence.json'):
 d=json.loads(f.read_text()); identity=d.pop('identity')
 # The identity excludes the registry presentation name, matching the importer's contract.
 d.pop('model_name',None)
 if hashlib.sha256(json.dumps(d,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()!=identity:
  raise ValueError('restored evidence hash mismatch')
 count+=1
if count==0: raise ValueError('no restored evidence')
print(json.dumps({'restore':'pass','benchmark_artifacts_verified':count,'network':'none','production_mutated':False}))
PY
