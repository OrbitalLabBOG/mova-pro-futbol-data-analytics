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

# Los receipts preceden al resultado: preservan incluso intentos fallidos o muertos.
/usr/local/bin/mova strategy attempts import
# Importar primero permite que el siguiente envelope selle research ya validado.
/usr/local/bin/mova strategy research import
/usr/local/bin/mova strategy deliberate import

deliberation_rc=0
/usr/local/bin/mova strategy deliberate enqueue || deliberation_rc=$?
if [[ $deliberation_rc -ne 0 && $deliberation_rc -ne 75 ]]; then
  exit "$deliberation_rc"
fi

# Sin ninguna request no se levanta Node/Codex. Una request persistente conserva
# el retry del worker, sea Researcher o Strategist+Critic.
if ! compgen -G "$research_root/inbox/*.request.json" >/dev/null; then
  exit 75
fi

# El host revalida estado, deadline y presupuesto por cada ejecución física.
# El worker no puede invocar Codex sin el permiso corto ligado al hash de request.
authorize_rc=0
/usr/local/bin/mova strategy attempts authorize || authorize_rc=$?
if [[ $authorize_rc -ne 0 && $authorize_rc -ne 75 ]]; then
  exit "$authorize_rc"
fi
if [[ $authorize_rc -eq 75 ]]; then
  exit 75
fi

worker_rc=0
docker compose --profile research run --rm --no-deps -T research || worker_rc=$?

/usr/local/bin/mova strategy attempts import
/usr/local/bin/mova strategy research import
/usr/local/bin/mova strategy deliberate import
if [[ $worker_rc -ne 0 && $worker_rc -ne 75 ]]; then
  exit "$worker_rc"
fi
if [[ $worker_rc -eq 75 ]]; then
  exit 75
fi
