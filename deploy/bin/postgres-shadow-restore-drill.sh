#!/usr/bin/env bash
set -euo pipefail
repo_dir=${MOVA_REPO_DIR:-/opt/orbital/services/mova-fpl}
backup_dir=${1:?usage: postgres-shadow-restore-drill.sh BACKUP_DIRECTORY}
backup_dir=$(realpath -e "$backup_dir")
cd "$repo_dir"
# A fresh private cluster, without runtime mounts, credentials or published ports.
image=postgres:17.11-bookworm@sha256:07edf880f0cf3f742c990d23faf92cb19e84923a8bce30f7d8e1a8ab63cae7b3
container="mova-dr-postgres-$(date -u +%Y%m%d%H%M%S)-$$"
cleanup() { docker rm -f "$container" >/dev/null 2>&1 || true; }
trap cleanup EXIT HUP INT TERM
python3 - "$backup_dir" <<'PY'
import hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1]); manifest_path=root/'manifest.json'; dump=root/'postgres-shadow.dump'
if manifest_path.is_symlink() or dump.is_symlink():
    raise SystemExit('unsafe restore files')
m=json.loads(manifest_path.read_text())
if m.get('schema') != 'mova-postgres-backup-v2' or not (m.get('inventory') or {}).get('tables'):
    raise SystemExit('content-sealed PostgreSQL v2 backup required')
with dump.open('rb') as f:
    digest=hashlib.file_digest(f,'sha256').hexdigest()
if digest != m['dump']['sha256'] or dump.stat().st_size != m['dump']['bytes']:
    raise SystemExit('PostgreSQL dump checksum or size mismatch')
PY
docker run -d --name "$container" --network none --user postgres \
  --read-only --cap-drop ALL --security-opt no-new-privileges:true \
  --memory 768m --cpus 0.50 --pids-limit 128 \
  --tmpfs /var/lib/postgresql/data:rw,size=2g,uid=999,gid=999 \
  --tmpfs /var/run/postgresql:rw,size=16m,uid=999,gid=999 \
  --tmpfs /tmp:rw,size=64m,mode=1777 \
  -e POSTGRES_HOST_AUTH_METHOD=trust -e POSTGRES_DB=mova_restore \
  -e PGDATA=/var/lib/postgresql/data/pgdata "$image" >/dev/null
ready=false
for _ in $(seq 1 60); do
  if docker exec "$container" pg_isready -U postgres -d mova_restore >/dev/null 2>&1; then
    ready=true; break
  fi
  sleep 1
done
[[ "$ready" == true ]]
docker exec -i "$container" pg_restore --exit-on-error --no-owner --no-acl \
  --username=postgres --dbname=mova_restore < "$backup_dir/postgres-shadow.dump"
python3 -m mova_fpl.ops.postgres_backup verify "$backup_dir" \
  --database mova_restore --user postgres --container "$container"
docker rm -f "$container" >/dev/null
trap - EXIT HUP INT TERM
echo "isolated PostgreSQL restore passed; disposable cluster removed"
