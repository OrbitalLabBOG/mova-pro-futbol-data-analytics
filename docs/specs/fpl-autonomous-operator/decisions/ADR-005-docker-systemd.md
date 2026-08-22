---
type: decision
name: "ADR-005 — Docker Compose y systemd en el VPS"
created: 2026-08-21
updated: 2026-08-21
tags: [mova, fpl, adr, docker, systemd]
status: proposed
---

# ADR-005 — Docker Compose y systemd en el VPS

## Decisión

Empaquetar engine y browser en contenedores separados y usar systemd para vida del stack y
timer persistente del `tick`.

## Razón

El host ofrece Python 3.12 y SQLite 3.45.1; el motor exige Python 3.13/CBC y `ops.db` en WAL
requiere SQLite ≥3.51.3 por el bug upstream de WAL-reset. Docker fija ambos runtimes;
systemd ofrece reinicio, historial, `Persistent=true` y control uniforme ya disponible en
el VPS.

## Alternativas

- conda en host: reproduce local, pero mezcla dependencias y dificulta restore;
- cron + scripts host: sencillo, pero débil en estado y diagnóstico;
- Kubernetes: desproporcionado para 2 CPU/una cuenta;
- Compose + systemd: seleccionado.

## Consecuencias

Dos imágenes, volúmenes y healthchecks que mantener. La imagen engine registra y valida
`sqlite_version()` al arrancar; host tools no tocan `ops.db`. El browser no comparte perfil
ni red pública con otros servicios.
