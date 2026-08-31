#!/usr/bin/env bash
set -euo pipefail

install -d -m 0750 -o 10001 -g 10001 /var/lib/mova-fpl /var/lib/mova-fpl/db
install -d -m 0750 -o 10001 -g 10001 \
  /var/lib/mova-fpl/runtime \
  /var/lib/mova-fpl/artifacts /var/lib/mova-fpl/artifacts/sources \
  /var/lib/mova-fpl/artifacts/models /var/lib/mova-fpl/artifacts/decisions \
  /var/lib/mova-fpl/artifacts/evidence \
  /var/lib/mova-fpl/artifacts/strategic-context
install -d -m 0700 -o 10002 -g 10002 /var/lib/mova-fpl/codex-home
install -d -m 2770 -o 10002 -g 10001 \
  /var/lib/mova-fpl/artifacts/research \
  /var/lib/mova-fpl/artifacts/research/inbox \
  /var/lib/mova-fpl/artifacts/research/outbox \
  /var/lib/mova-fpl/artifacts/research/archive \
  /var/lib/mova-fpl/artifacts/research/quarantine \
  /var/lib/mova-fpl/artifacts/research/logs
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
for role_secret in postgres-app-password postgres-readonly-password; do
  if [[ ! -e "/etc/mova-fpl/$role_secret" ]]; then
    umask 077
    openssl rand -hex 32 > "/etc/mova-fpl/$role_secret"
    echo "created /etc/mova-fpl/$role_secret (content not displayed)"
  fi
  chown root:10001 "/etc/mova-fpl/$role_secret"
  chmod 0640 "/etc/mova-fpl/$role_secret"
done
if [[ -e /etc/mova-fpl/odds-api-key ]]; then
  chown root:10001 /etc/mova-fpl/odds-api-key
  chmod 0640 /etc/mova-fpl/odds-api-key
else
  echo "warning: /etc/mova-fpl/odds-api-key is absent; market_odds will remain degraded"
fi
if [[ ! -e /etc/mova-fpl/alert-webhook.json ]]; then
  install -m 0640 -o root -g 10001 \
    deploy/alert-webhook.disabled.json /etc/mova-fpl/alert-webhook.json
  echo "created disabled /etc/mova-fpl/alert-webhook.json"
fi
chown root:10001 /etc/mova-fpl/alert-webhook.json
chmod 0640 /etc/mova-fpl/alert-webhook.json

echo "host directories ready; existing runtime.env/deploy.env were preserved"
