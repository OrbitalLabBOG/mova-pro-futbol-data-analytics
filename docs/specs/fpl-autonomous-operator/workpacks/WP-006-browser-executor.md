---
type: workpack
name: "WP-006 — Executor browser y verificación"
created: 2026-08-21
updated: 2026-08-31
tags: [mova, fpl, workpack, agent-browser, verification]
status: in_progress
---

# WP-006 — Executor browser y verificación

## Objetivo

Aplicar envelopes aprobados en FPL con un perfil dedicado, interacción por bloques y prueba
post-reload, sin guardar secretos ni reintentar ambiguamente.

## Dependencias

WP-001..003, WP-005, compliance gate aprobado y autorización externa explícita.

## Entregables

- interface `Executor` con adapters disabled/human/browser;
- state reader privado y preflight de identidad/entry;
- workflows para XI/banca/C/VC, transferencias y chips;
- DOM fixtures y contract tests;
- evidence bundle y verifier exacto;
- runbook de auth, DOM drift, timeout y ambiguous write.

## Criterios de aceptación

- nunca escribe contraseña/OTP/MFA;
- pre-state distinto al esperado bloquea;
- modal de hit/chip distinto al envelope bloquea;
- un toast sin reload match no marca success;
- ejecución ambigua no reintenta antes de reconciliar;
- hard stop impide nuevas mutaciones;
- screenshot/DOM post-reload tienen hash y ubicación privada;
- 3 rehearsals supervised por nivel antes de promoverlo.

## Estado de implementación

- `ExecutionPlan`, reserva apply-once, claim/lease, verifier post-reload y ledger están
  desplegados en shadow;
- el probe DOM sanitizado cruza GET privado, orden posicional y 15 controles visibles;
- el planner puro genera swaps mínimos sin guardar refs accessibility;
- el commit se limita a un click y permanece deshabilitado si existe cualquier blocker;
- captain/vice tienen control semántico vivo y un primer rehearsal; autonomía no promovida;
- XI/banca y R3 tienen contrato y un primer probe, pero entrypoints y promoción siguen cerrados;
- el drill hermético DOM/save prueba deriva, pre-state nuevo, `ambiguous`, P0 y no-retry;
- los tres rehearsals supervisados por capacidad siguen pendientes; no se promovieron controles.
