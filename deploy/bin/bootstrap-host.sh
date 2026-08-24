#!/usr/bin/env bash
set -euo pipefail

install -d -m 0750 -o 10001 -g 10001 /var/lib/mova-fpl /var/lib/mova-fpl/db
install -d -m 0750 -o 10001 -g 10001 \
  /var/lib/mova-fpl/runtime \
  /var/lib/mova-fpl/artifacts /var/lib/mova-fpl/artifacts/sources \
  /var/lib/mova-fpl/artifacts/models /var/lib/mova-fpl/artifacts/decisions \
  /var/lib/mova-fpl/artifacts/evidence
install -d -m 0700 -o 999 -g 999 /var/lib/mova-fpl/postgres
install -d -m 0700 -o 1000 -g 1000 /var/lib/mova-fpl/browser-profile
install -d -m 0750 -o 10001 -g 10001 /opt/orbital/backups/mova-fpl
install -d -m 0750 -o root -g root /etc/mova-fpl

if [[ ! -e /etc/mova-fpl/runtime.env ]]; then
  install -m 0640 -o root -g root deploy/runtime.env.example /etc/mova-fpl/runtime.env
fi
if [[ ! -e /etc/mova-fpl/deploy.env ]]; then
  install -m 0640 -o root -g root deploy/deploy.env.example /etc/mova-fpl/deploy.env
fi
if [[ ! -e /etc/mova-fpl/postgres-password ]]; then
  umask 077
  openssl rand -hex 32 > /etc/mova-fpl/postgres-password
  chown root:10001 /etc/mova-fpl/postgres-password
  chmod 0640 /etc/mova-fpl/postgres-password
  echo "created /etc/mova-fpl/postgres-password (content not displayed)"
fi
chown root:10001 /etc/mova-fpl/postgres-password
chmod 0640 /etc/mova-fpl/postgres-password
if [[ -e /etc/mova-fpl/odds-api-key ]]; then
  chown root:10001 /etc/mova-fpl/odds-api-key
  chmod 0640 /etc/mova-fpl/odds-api-key
else
  echo "warning: /etc/mova-fpl/odds-api-key is absent; market_odds will remain degraded"
fi

echo "host directories ready; existing runtime.env/deploy.env were preserved"
