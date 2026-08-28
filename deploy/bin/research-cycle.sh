#!/usr/bin/env bash
set -euo pipefail

repo_dir=${MOVA_REPO_DIR:-/opt/orbital/services/mova-fpl}
research_root=${MOVA_RESEARCH_ROOT:-/var/lib/mova-fpl/artifacts/research}
cd "$repo_dir"

enqueue_rc=0
/usr/local/bin/mova strategy research enqueue || enqueue_rc=$?
if [[ $enqueue_rc -ne 0 && $enqueue_rc -ne 75 ]]; then
  exit "$enqueue_rc"
fi

# Un tick sin request no levanta Node/Codex. Primero importa cualquier resultado
# huérfano; una request persistente sí conserva el retry del worker.
if [[ $enqueue_rc -eq 75 ]]; then
  /usr/local/bin/mova strategy research import
  if ! compgen -G "$research_root/inbox/research_*.request.json" >/dev/null; then
    exit 75
  fi
fi

worker_rc=0
docker compose --profile research run --rm --no-deps -T research || worker_rc=$?
if [[ $worker_rc -ne 0 && $worker_rc -ne 75 ]]; then
  exit "$worker_rc"
fi

/usr/local/bin/mova strategy research import
if [[ $worker_rc -eq 75 ]]; then
  exit 75
fi
