---
type: project
name: "MOVA FPL Autonomous Operator 2026/27 — Specification Index"
created: 2026-08-21
updated: 2026-08-31
tags: [mova, fpl, autonomy, observability, specification]
status: active-shadow
---

# MOVA FPL Autonomous Operator 2026/27

Especificación de la iniciativa sucesora del motor FPL v1. Define cómo operar el equipo
durante toda la temporada con ciclos autónomos, trazables y seguros, sin cambiar la lógica
de decisión que ya vive en `mova_fpl/`.

La especificación ya tiene una primera implementación desplegada en el VPS en modo
**shadow A0**. Esto autoriza recolección, análisis, modelos y evidencia; no autoriza
cambios en la cuenta FPL. Supabase queda fuera del runtime: solo conserva el seguimiento
PM de construcción del proyecto.

## Estado

| Campo | Valor |
| --- | --- |
| Versión | 0.36 |
| Estado | `active-shadow` |
| Riesgo | alto: cuenta externa, deadlines irreversibles y sesión autenticada |
| Business owner | Julián Zuluaga |
| Aprobación técnica | pendiente de Nicolás Buitrago |
| Temporada | 2026/27 |
| Equipo | `losmillosFPL`, `entry_id=3609854` |
| Primera aplicación prevista | GW2; GW1 ya fue montada y sellada manualmente |
| Corte de construcción | Harness read-only A0 cerrado; operación y evidencia longitudinal continúan |

## Documentos

| Documento | Contenido |
| --- | --- |
| [00-brief.md](00-brief.md) | objetivo, alcance, hechos, riesgos y éxito |
| [01-requirements.md](01-requirements.md) | requisitos funcionales, calidad, seguridad y operación |
| [02-architecture.md](02-architecture.md) | componentes, estado, scheduling, ejecución y fallos |
| [03-data-and-observability.md](03-data-and-observability.md) | datos, trazas, métricas, SLO, alertas y retención |
| [04-readiness-and-rollout.md](04-readiness-and-rollout.md) | readiness actual, gates y rollout por niveles |
| [05-source-register.md](05-source-register.md) | reglas y referencias técnicas verificadas |
| [06-traceability.md](06-traceability.md) | requisitos → decisiones → workpacks → evidencia esperada |
| [07-deployment-evidence.md](07-deployment-evidence.md) | acta verificable del primer despliegue shadow en VPS |
| [08-agentic-research-harness.md](08-agentic-research-harness.md) | coordinador de investigación, backends, contratos, persistencia y roadmap |
| [09-agent-harness-implementation-spec.md](09-agent-harness-implementation-spec.md) | implementación exacta del harness, workers, budgets, seguridad, evals y despliegue |
| [10-autonomous-harness-v1.md](10-autonomous-harness-v1.md) | **hoja de ruta canónica**: Postgres, CLI/skill, roles, memoria, costos, ejecución y mejora continua |
| [11-hv1-01-deployment-evidence.md](11-hv1-01-deployment-evidence.md) | cierre verificable del contrato `mova`, skill y rollout VPS |
| [12-gw2-preliminary-review.md](12-gw2-preliminary-review.md) | preliminar GW2, señales de modelo y guardrail de settlement |
| [13-hv1-02a-postgres-shadow-evidence.md](13-hv1-02a-postgres-shadow-evidence.md) | evidencia de schema, import, backup y restore del store shadow |
| [14-hv1-03a-data-service-evidence.md](14-hv1-03a-data-service-evidence.md) | cierre del collector autónomo: FPL, odds, calendario, eventos, calidad y observabilidad |
| [15-hv1-04-05-strategic-research-evidence.md](15-hv1-04-05-strategic-research-evidence.md) | season plan, manifest sellado y primera investigación Codex validada en el VPS |
| [16-hv1-06a-decision-envelope-evidence.md](16-hv1-06a-decision-envelope-evidence.md) | bundle de tres candidatos, Validator determinista y primer envelope vivo |
| [17-hv1-06b-deliberation-evidence.md](17-hv1-06b-deliberation-evidence.md) | Strategist + Critic acotados, intervención shadow y replay vivo corregido |
| [20-hv1-07d-dom-probe.md](20-hv1-07d-dom-probe.md) | DOM probe autenticado y planner R2 fail-closed |
| [21-hv1-08-improvement-rollout.md](21-hv1-08-improvement-rollout.md) | Gate propuesta→lección, costos explícitos y reconciliación de incidentes |
| [22-hv1-08-budget-rollout.md](22-hv1-08-budget-rollout.md) | Budgets persistentes, reservas atómicas y observabilidad de costo |
| [23-hv1-08-causal-reviewer-rollout.md](23-hv1-08-causal-reviewer-rollout.md) | Reviewer causal post-settlement y propuestas multi-GW |
| [24-hv1-08-model-release-rollout.md](24-hv1-08-model-release-rollout.md) | Release de modelos con hashes, shadow pareado, promoción y rollback |
| [25-hv1-03b-model-ops-rollout.md](25-hv1-03b-model-ops-rollout.md) | Facade train/predict/explain/evaluate y candidato fail-closed |
| [26-hv1-05b-sealed-research-rollout.md](26-hv1-05b-sealed-research-rollout.md) | Fetch/locator sellado, coverage explícita y rollout v2 fail-closed |
| [27-hv1-09-autonomy-readiness-rollout.md](27-hv1-09-autonomy-readiness-rollout.md) | Gate único de elegibilidad técnica, blockers y evidencia de promoción |
| [28-hv1-07e-r3-contract-rollout.md](28-hv1-07e-r3-contract-rollout.md) | Contrato R3 tipado, probe vivo read-only y driver de validación sin entrypoint productivo |
| [29-hv1-05c-agent-recovery-rollout.md](29-hv1-05c-agent-recovery-rollout.md) | Recuperación viva de Researcher v2 y validación Strategist/Critic sobre GW3 |
| [30-hv1-08b-budget-observability-rollout.md](30-hv1-08b-budget-observability-rollout.md) | Semántica de costos agentic, overruns y reservas huérfanas observables |
| [31-hv1-07f-browser-rehearsal-ledger-rollout.md](31-hv1-07f-browser-rehearsal-ledger-rollout.md) | Ledger durable anti-inflación y primer rehearsal browser vivo |
| [32-hv1-02b-read-cutover-drill-rollout.md](32-hv1-02b-read-cutover-drill-rollout.md) | Cutover/rollback reversible de lectura PostgreSQL |
| [33-hv1-02c-postgres-role-separation-rollout.md](33-hv1-02c-postgres-role-separation-rollout.md) | Identidades runtime least-privilege y drill con readonly real |
| [34-hv1-07g-capability-probes-rollout.md](34-hv1-07g-capability-probes-rollout.md) | Importadores allowlisted y primeros probes vivos de lineup/R3 |
| [36-hv1-01b-alert-safety-maintenance.md](36-hv1-01b-alert-safety-maintenance.md) | Outbox recuperable, acuse, safety summary y cleanup conservador |
| [37-hv1-09b-watchdog-resilience-drill.md](37-hv1-09b-watchdog-resilience-drill.md) | P0 de scheduler, delivery fail-closed y rehearsal hermético de recuperación |
| [38-hv1-09c-api-recovery-drill.md](38-hv1-09c-api-recovery-drill.md) | Caída real del API, recuperación automática e import de evidencia allowlisted |
| [39-hv1-09d-postgres-recovery-drill.md](39-hv1-09d-postgres-recovery-drill.md) | Caída real del PostgreSQL shadow, continuidad SQLite y recuperación con paridad |
| [40-hv1-09e-snapshot-rejection-drill.md](40-hv1-09e-snapshot-rejection-drill.md) | Rechazo hermético de snapshots alterados, corruptos, traversal y symlinks |
| [41-hv1-09f-browser-failure-drill.md](41-hv1-09f-browser-failure-drill.md) | Deriva DOM, pre-state cambiado y save ambiguo con apply-once fail-closed |
| [42-hv1-09g-browser-recovery-drill.md](42-hv1-09g-browser-recovery-drill.md) | Caída real de Chromium/noVNC, recuperación de sesión y restauración on-demand |
| [43-hv1-09h-combined-recovery-drill.md](43-hv1-09h-combined-recovery-drill.md) | Outage conjunto API+PostgreSQL+browser con continuidad SQLite y restore completo |
| [44-hv1-10-harness-scorecard-rollout.md](44-hv1-10-harness-scorecard-rollout.md) | Scorecard unificado de calidad, costo, aprendizaje y autoridad del harness |
| [45-hv1-10b-budget-overrun-lifecycle.md](45-hv1-10b-budget-overrun-lifecycle.md) | Ledger auditable de revisión de overruns y optimización acotada del Researcher |
| [46-hv1-11-orchestration-audit.md](46-hv1-11-orchestration-audit.md) | Grafo agentic observable y rehearsal hermético de orden, fail-closed y deadline |
| [47-hv1-12-external-alert-channel.md](47-hv1-12-external-alert-channel.md) | Adaptador webhook opt-in, redacción, rehearsal hermético y gate de destino real |
| [48-hv1-12b-live-alert-proof.md](48-hv1-12b-live-alert-proof.md) | Live-ping apply-once ligado al destino, outbox aislado y gate contra falsa configuración |
| [49-hv1-06d-orphan-deliberation-recovery.md](49-hv1-06d-orphan-deliberation-recovery.md) | Recuperación de request huérfano, corte de replay costoso y doble barrera pre-worker |
| [50-hv1-09i-agent-queue-watchdog.md](50-hv1-09i-agent-queue-watchdog.md) | Watchdog independiente de cola agentic, incidente P1, API, métricas y drill 10/10 |
| [51-hv1-09j-agent-attempt-ledger.md](51-hv1-09j-agent-attempt-ledger.md) | Recibos append-only, logs por intento y replay automático limitado a dos ejecuciones |
| [52-hv1-10c-physical-attempt-accounting.md](52-hv1-10c-physical-attempt-accounting.md) | Presupuesto por ejecución física, estimación conservadora y compatibilidad legacy sin doble conteo |
| [53-hv1-10d-pre-attempt-authorization.md](53-hv1-10d-pre-attempt-authorization.md) | Permiso host→worker por intento con budget, deadline, expiración e identidad sellada |
| [54-hv1-09k-attempt-permit-watchdog.md](54-hv1-09k-attempt-permit-watchdog.md) | Reconciliación de permisos vencidos y detección P1 de permisos alterados, huérfanos o starts estancados |
| [55-hv1-09l-reboot-recovery-gate.md](55-hv1-09l-reboot-recovery-gate.md) | Workflow bifásico y gate honesto para recuperación tras un reboot real del VPS |
| [56-hv1-02d-offsite-backup-readiness.md](56-hv1-02d-offsite-backup-readiness.md) | Backup cifrado off-host opt-in, estado sanitizado y contrato de restore verificable |
| [57-hv1-09m-final-runtime-closeout.md](57-hv1-09m-final-runtime-closeout.md) | Recuperación de la cola agentic, refresh privado, reboot real 5/5 y cierre verificable del runtime |
| [58-hv1-08c-agent-cadence-rollout.md](58-hv1-08c-agent-cadence-rollout.md) | Tres slots agentic y una deliberación por research importado |
| [59-hv1-13-operations-cockpit-rollout.md](59-hv1-13-operations-cockpit-rollout.md) | Cockpit, triage, acceso web privado y sentinel deadline-aware |
| [60-hv1-13b-owner-dashboard.md](60-hv1-13b-owner-dashboard.md) | Dashboard ejecutivo público, semántica verde/rojo y diagnóstico loopback-only |
| [contracts/](contracts/) | JSON Schemas máquina para request, result y signal |
| [decisions/](decisions/) | decisiones arquitectónicas propuestas |
| [workpacks/](workpacks/) | unidades de implementación y criterios todavía pendientes |

## Principio rector

La autonomía no significa libertad para improvisar. Significa que cada jornada puede
avanzar sin intervención rutinaria porque las fuentes, decisiones, límites, reintentos,
verificaciones y criterios de parada están codificados y son observables. Para ejecución,
priorización y tareas nuevas manda
[Autonomous Harness v1](10-autonomous-harness-v1.md); 08 y 09 son referencias de diseño y
hardening diferido.
