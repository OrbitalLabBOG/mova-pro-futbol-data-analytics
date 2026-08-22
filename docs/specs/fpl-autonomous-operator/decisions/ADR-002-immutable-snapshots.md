---
type: decision
name: "ADR-002 — Snapshots inmutables y manifest raíz"
created: 2026-08-21
updated: 2026-08-21
tags: [mova, fpl, adr, data-lineage]
status: proposed
---

# ADR-002 — Snapshots inmutables y manifest raíz

## Decisión

Toda entrada usada en una decisión se conserva byte a byte, se direcciona por SHA-256 y se
une mediante un manifest canónico cuyo hash identifica la corrida.

## Contexto

El catálogo vivo pasó de 599 a 600 jugadores entre verificaciones. Guardar solo la versión
“más reciente” impediría reproducir qué vio el sistema.

## Alternativas

- sobreescribir JSON vigente: descartado por pérdida de evidencia;
- guardar solo filas normalizadas: descartado porque parser y fuente no se pueden reauditar;
- raw + normalizado + manifest: seleccionado.

## Consecuencias

Más disco y política de retención, a cambio de replay, auditoría de drift e idempotencia
estable.
