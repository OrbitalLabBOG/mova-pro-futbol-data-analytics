---
type: decision
name: "ADR-004 — Autonomía por niveles y gate de cumplimiento"
created: 2026-08-21
updated: 2026-08-21
tags: [mova, fpl, adr, compliance, browser]
status: proposed
---

# ADR-004 — Autonomía por niveles y gate de cumplimiento

## Decisión

Separar modos `shadow`, `supervised`, `guarded` y `autonomous`, y niveles A0–A3. Ningún
write se habilita sin `compliance_gate=approved`, feature flag del nivel y ausencia de kill
switch.

## Contexto

Los términos vigentes incluyen prohibición expresa sobre sistemas automatizados que acceden
y extraen información, control personal de la cuenta y sanciones por breach. La interpretación
y aceptación no son decisiones técnicas.

## Consecuencias

La arquitectura soporta autonomía total, pero el default es seguro. La aprobación de un
nivel queda auditada y puede revocarse sin redeploy. Un perfil autenticado persistente evita
guardar contraseñas, pero no elimina el riesgo contractual.
