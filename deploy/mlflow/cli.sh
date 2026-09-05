#!/usr/bin/env bash
set -euo pipefail
cd /opt/orbital/services/mova-mlflow
set -a
source /etc/mova-mlflow/deploy.env
set +a
exec docker compose -f deploy/mlflow/compose.yaml "$@"
