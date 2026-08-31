---
type: workpack
name: "WP-001 — Runtime reproducible y deploy VPS"
created: 2026-08-21
updated: 2026-08-31
tags: [mova, fpl, workpack, docker, vps]
status: active-shadow
---

# WP-001 — Runtime reproducible y deploy VPS

## Objetivo

Reproducir motor y browser en dos imágenes fijadas, con Compose, volúmenes, red privada,
healthchecks, límites y units systemd.

## Dependencias

G0 aprobado; remote Git sincronizado con el SHA de release.

## Entregables

- imagen engine Python 3.13/CBC/SQLite ≥3.51.3 y browser Node/Chromium/agent-browser;
- Compose hardened, secrets externos y volúmenes dedicados;
- service/timer systemd con `Persistent=true`;
- procedimiento de build, deploy, rollback, backup y restore.

## Criterios de aceptación

- suite rápida y collector smoke pasan dentro de la imagen;
- startup y job de backup reportan SQLite ≥3.51.3 y fallan cerrado con una versión menor;
- `docker compose config` y healthchecks pasan;
- reboot retoma el timer sin jobs duplicados;
- CDP no es accesible fuera de la red privada;
- resource limits evitan presión material sobre servicios existentes;
- admission gates bloquean jobs pesados bajo 2.5 GiB `MemAvailable` o 20 GiB de disco y
  generan alerta observable;
- el deploy reporta git SHA e image digest exactos.

## No incluye

Tablas, browser login, writes FPL ni activar timers productivos antes del control plane.

## Estado verificado

Engine/browser fijados, Compose hardened, secrets externos, límites, healthchecks, units
persistentes, backup/restore, SHA/digest y gates de recursos operan en el VPS. El watchdog v2
abre un único P0 cuando falta o vence el heartbeat, entrega el outbox fuera de la transacción y
resuelve el incidente tras recuperación. El rehearsal hermético prueba esa cadena sin mutar el
runtime. HV1-09L desplegó la preparación con TTL, backups y estado sellado, más una unidad boot-time
que exige stack, ocho timers, tick posterior, integridad, paridad, revisión, controles, fingerprint
e idempotencia antes de importar el escenario. El workpack permanece `active-shadow`: falta
autorizar y ejecutar el reboot real; la copia cifrada off-host sigue sujeta a Q-04.
