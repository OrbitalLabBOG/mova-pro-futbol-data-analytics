---
type: adr
name: ADR-022 — Harness mínimo en el VPS (copiloto sin watchdog, tick ni DR)
created: 2026-11-25
updated: 2026-11-25
status: accepted
owner: Julian Zuluaga
extends: docs/specs/fpl-autonomous-operator/decisions/ADR-021-copilot-operating-model.md
---

# Contexto

ADR-021 dejó el modo copiloto, pero el VPS siguió con tick cada 5 min, watchdog,
dr-status horario, captura privada cada 5 min, postgres-sync y poda horaria. Ese
aparato generaba ruido: tres unidades `failed`, cuatro incidentes abiertos y un brief
con `authority_unsafe` por P0/P1 de heartbeat, DR, colas de agentes y un Save
autónomo que ya no existe.

# Decisión

1. **El VPS solo garantiza:** colector (`mova-fpl-collector.timer`), analytics/ML
   (`mova-fpl-analytics.timer`, solo inferencia), pila Postgres + API
   (`mova-fpl-stack.service`), memoria operativa (`ops.db`) y un backup diario simple.
2. **Timers retirados:** tick, watchdog, dr-status, private-state, postgres-sync,
   backup-retention (la poda se integra al backup diario) y delivery. Se borran sus
   unidades; `install-systemd.sh` las deshabilita (`RETIRED_UNITS`). Quedan `research`
   (on-demand) y `reboot-recovery` (inerte).
3. **Backup diario** (04:17 Bogotá): SQLite verificado (`ops.db`, `trace.db`,
   `fpl_canonical.db`) + `pg_dump`, con poda local a 7–14 días en el mismo job.
   Offsite (restic, opt-in) semanal. RPO de doctor/DR: **36 h** (antes 7 h).
4. **Doctor delgado.** Requeridos: colector sano (`fpl_official`), Postgres y API
   arriba, `ops.db` ok, joblibs de minutos/puntos, disco ≥ 20 GiB, backup < 36 h y las
   unidades `stack` + `collector.timer`. `scheduler_heartbeat`, cola de agentes, DR,
   estado privado, paridad shadow y resultados de servicios fallidos ya no son FAIL
   requeridos.
5. **Seguridad/brief.** `build_safety` ignora, para `unsafe`/`authority_unsafe`, los
   incidentes del harness retirado (heartbeat, DR, colas, deadline autónomo,
   "Ejecución FPL ambigua", Shadow decision, disco bajo). Siguen visibles en `status`.
6. **Alerta única, sin watchdog.** Al final de `mova collect all` (cada 15 min) corre
   `mova alerts health`: si `fpl_official` lleva > 6 h sin sano o el disco < 20 GiB,
   escribe en journal y en el sink Slack/webhook configurado, con cooldown de 12 h. No
   abre incidentes.
7. **Estado privado on-demand.** `mova private-state capture --force --actor --reason
   --idempotency-key` (host, envuelve `collect-private-team-state.sh --force`, con
   lock y cooldown). `week brief|acta --capture-private-state` lo invoca antes.
8. **Limpieza de incidentes.** `mova incidents close-obsolete` cierra con actor, razón
   e idempotencia: "Ejecución FPL ambigua", "Backup recovery observation unhealthy",
   "Shadow decision falló". "Local storage headroom low" solo si hay ≥ 28 GiB libres.

# Consecuencias

- El módulo de tick/watchdog y la cadena `execute dispatch|prepare|…` siguen en el
  código como legacy a demanda; ninguna unidad, doctor ni safety los exige. Su borrado
  queda para un PR posterior.
- Se conserva `execute manual-package|record-manual|preflight`.
- Nada se escribe en FPL sin el OK explícito de Julián (sin cambios).

# Rollout

Requiere OK de Julián; ver [vps.md](../../../operations/vps.md#rollout-adr-022-harness-mínimo).
