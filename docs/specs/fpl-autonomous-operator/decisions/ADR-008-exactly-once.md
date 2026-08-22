---
type: decision
name: "ADR-008 — Exactly-once observable para mutaciones"
created: 2026-08-21
updated: 2026-08-21
tags: [mova, fpl, adr, idempotency, safety]
status: proposed
---

# ADR-008 — Exactly-once observable para mutaciones

## Decisión

No prometer exactly-once de red. Garantizar **un envelope lógico único**, intento registrado,
reconciliación antes de retry y estado post-reload igual al esperado. Hard stop T-15m.

## Razón

La UI puede confirmar y perder respuesta, o devolver toast sin persistir. Repetir un click
ambiguo puede duplicar transferencias o activar un chip.

## Protocolo

1. unique decision+action level;
2. claim atómico;
3. pre-state fingerprint;
4. un intento;
5. reload/reconcile;
6. solo si el estado demuestra no-aplicación y queda ventana, un retry nuevo enlazado;
7. evidencia post-state.

## Consecuencias

Ante ambigüedad se prioriza preservar el último estado conocido. El sistema puede quedar
bloqueado y requerir intervención, que es preferible a una mutación duplicada.
