#!/usr/bin/env bash
set -euo pipefail

install -d -m 0750 -o 10001 -g 10001 /var/lib/mova-fpl /var/lib/mova-fpl/db
install -d -m 0750 -o 10001 -g 10001 \
  /var/lib/mova-fpl/runtime \
  /var/lib/mova-fpl/artifacts /var/lib/mova-fpl/artifacts/sources \
  /var/lib/mova-fpl/artifacts/models /var/lib/mova-fpl/artifacts/decisions \
  /var/lib/mova-fpl/artifacts/evidence
install -d -m 0700 -o 1000 -g 1000 /var/lib/mova-fpl/browser-profile
install -d -m 0750 -o 10001 -g 10001 /opt/orbital/backups/mova-fpl
install -d -m 0750 -o root -g root /etc/mova-fpl

if [[ ! -e /etc/mova-fpl/runtime.env ]]; then
  install -m 0640 -o root -g root deploy/runtime.env.example /etc/mova-fpl/runtime.env
fi
if [[ ! -e /etc/mova-fpl/deploy.env ]]; then
  install -m 0640 -o root -g root deploy/deploy.env.example /etc/mova-fpl/deploy.env
fi

echo "host directories ready; existing runtime.env/deploy.env were preserved"
