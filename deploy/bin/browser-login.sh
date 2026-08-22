#!/usr/bin/env bash
set -euo pipefail

repo_dir=${MOVA_REPO_DIR:-/opt/orbital/services/mova-fpl}
exec "$repo_dir/deploy/bin/browser-session.sh" login
