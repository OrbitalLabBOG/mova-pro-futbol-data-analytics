---
type: adr
name: ADR-021 — Modelo operativo copiloto con tools y memoria
created: 2026-11-25
updated: 2026-11-25
status: accepted
owner: Julian Zuluaga
supersedes: docs/specs/fpl-autonomous-operator/10-autonomous-harness-v1.md
plan: docs/plans/operator-tools-refactor.md
---

# Contexto

Al 25/11/2026 (GW11 cerrada, GW12 siguiente) el harness autónomo seguía armado en
el VPS: timer de delivery cada 5 minutos en scope `lineup-v1`, research por timer
cada 15 minutos, sesión FPL vencida (`FPL_AUTH_REQUIRED`) y un collector privado que
fallaba de forma repetida. El código nunca tuvo auto-promoción (`readiness.py`
publica `promotion_is_automatic: False`); la autonomía vivía en los controles de
`ops.db` y en esos dos timers.

Julián decidió dejar de perseguir un Save autónomo por jornada. El valor está en
datos, modelos y memoria confiables, y en una decisión semanal que él valida.

# Decisión

1. **Copiloto por defecto.** `RuntimeConfig.operating_model` vale `copilot` salvo el
   opt-in legacy `MOVA_ENABLE_SCHEDULED_DELIVERY` (que además exige browser writes y
   compliance aprobado). `DeliveryService.dispatch` devuelve
   `blocked/copilot_mode` como primer gate. `status`, `safety` y `cockpit` publican
   `operating_model`.
2. **Operador.** Un asistente de IA (el Grok Bot de Julián, que orquesta Claude Code
   para cambios de código) opera MOVA cada GW con el catálogo `mova tools --json`
   (`mova-tools-v1`) y la memoria de `ops.db`. Propone XI, C/VC, transferencias y
   chip con razones; **nada se escribe en FPL sin el OK explícito de Julián** sobre un
   plan concreto.
3. **Única tool `write-fpl`:** la skill `fpl-web-ops`. Ningún comando del CLI escribe
   en FPL. `browser_writes`/`action_level` gobiernan solo el driver automático legacy;
   en copiloto quedan fail-closed (`browser_writes=false`, A0) y la operación visual
   la autoriza el OK de Julián, no un control.
4. **Memoria explícita.** Cada GW deja una nota `decision` (`mova memory note add`,
   tabla append-only `copilot_strategy_notes`, espejo Postgres `agent.strategy_notes`)
   y, si hay estado privado y evidencia, un paquete manual v2
   (`mova execute manual-package`) registrado con `mova execute record-manual`.
   Después de `data_checked`: `analytics reconcile`, `review settle-auto|gw` y nota
   `post_mortem`.
5. **Retiro de timers.** Se eliminan `mova-fpl-delivery.timer` y
   `mova-fpl-research.timer` versionados. `install-systemd.sh` los deshabilita y
   borra de forma idempotente. Research y deliberación pasan a on-demand.
6. **Qué se queda en el VPS:** collectors público y privado, timers de analytics/ML,
   tick (envelope + preflight como memoria), `ops.db`/`trace.db`/backups, API de datos
   y watchdog (solo salud; el recibo manual sigue contando como completado).

# Ciclo semanal

`week brief --json` → `week acta` (+ `strategy`/`research`/`deliberate` a demanda) →
propuesta con razones → validación con Julián → `fpl-web-ops` (solo con OK) →
`memory note add --kind decision` (siempre) + `execute manual-package` +
`execute record-manual` (si hay estado privado/evidencia) → tras `data_checked`:
`analytics reconcile`, `review settle-auto|gw`, `memory note add --kind post_mortem`.
Runbook: [gameweek.md](../../../operations/gameweek.md).

# Consecuencias

- Se conserva el código de la cadena de delivery
  (`execute dispatch|prepare|claim|ui-plan|begin|finalize|fail`, `rehearsal*`,
  `delivery-cycle.sh`, drivers R2/R3) como **legacy opt-in**: no está en el catálogo,
  falla cerrado en copiloto y no se recomienda en skills ni runbooks.
- `readiness`, scorecards y drills siguen siendo diagnóstico; ya no son un camino de
  promoción hacia la autonomía.
- `record-manual` v2 exige pre/post team state privados: si la sesión FPL está vencida
  el registro manual no es posible y la nota `decision` es la única memoria de la GW.
- Las ADR 014–019 (delivery acotado, campañas de continuidad) quedan como antecedentes;
  ADR-020 (recuperación de sesión y cierre manual atribuido) sigue vigente.

# Rollout

Requiere OK explícito de Julián: `git pull`, `install-systemd.sh` y reset de controles
con actor/razón (`delivery_scope`, `delivery_policy`, `browser_writes`,
`action_level`, `mode`). Procedimiento y verificación en
[vps.md](../../../operations/vps.md#rollout-adr-021-modelo-copiloto).

# Validación

`tests/test_delivery.py`, `test_operator_contract.py`, `test_cockpit.py`,
`test_research_worker_contract.py`, `test_host_probe.py`, `test_tools_catalog.py`,
`test_week_brief.py`, `test_strategy_notes.py`, `test_manual_package.py` y
`test_operator_docs.py` (skills y runbook no recomiendan la cadena legacy).
