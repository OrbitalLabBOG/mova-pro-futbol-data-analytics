---
type: evidence
name: "HV1-02a — PostgreSQL shadow"
created: 2026-08-23
updated: 2026-08-23
tags: [mova, fpl, hv1-02, postgres, evidence]
status: deployed-shadow
---

# Evidencia HV1-02a — PostgreSQL shadow

## Alcance

Este corte crea la base durable candidata y prueba su import/recuperación sin cambiar el
writer oficial SQLite ni la autonomía `shadow / A0`. No incluye repository adapter, dual-read,
cutover ni escrituras browser.

## Implementación

- PostgreSQL 17.11 Bookworm fijado por digest y red Docker interna sin host port;
- siete schemas y 29 tablas fuente importadas mediante una migración con checksum;
- snapshots SQLite consistentes, manifest SHA-256 e import transaccional/idempotente;
- CLI `mova postgres migrate|import|status|verify`;
- backup `pg_dump -Fc` y restore drill en una base temporal;
- chequeos opcionales del store y container en `mova doctor`;
- runbook y contrato explícito de rollback a SQLite.

## Evidencia pre-deploy

| Check | Resultado |
| --- | --- |
| Suite hermética | `682 passed, 79 deselected` |
| Compose | configuración válida |
| Shell | todos los scripts `bash -n` válidos |
| Migración limpia | PostgreSQL `17.11`; migration `001` aplicada |
| Import integración | 29/29 tablas con conteos iguales; invariantes `pass` |
| Verify integración | artefactos, tres SQLite y 29 conteos `pass` |
| Idempotencia | segunda clave idéntica reutiliza el import |
| Backup | dump custom y catálogo legible |
| Restore drill | restauración en `mova_restore_*` y limpieza automática |

La integración local usó datos fixture descartables antes de desplegar la revisión versionada.

## Evidencia del VPS

Despliegue verificado el 2026-08-23 sobre la revisión `e737bda9f904436a1f0a7433882a0f196ec5d281`.

| Check | Resultado |
| --- | --- |
| PostgreSQL | `17.11`, healthy, `max_connections=30`, sin puerto publicado |
| Schemas | `mova_meta`, `raw`, `analytics`, `game`, `research`, `agent`, `ops` |
| Import final | `pgimport_5c573078ad284196ac687b099eeeb883`, transacción completa |
| Paridad | 29/29 tablas con conteos iguales e invariantes `pass` |
| Histórico canónico | 253.890 filas; temporadas 2016-17 a 2025-26 |
| Agregados canónicos | 317.988 puntos y 7.492.730 minutos, sin drift |
| Traza histórica | 46 agent runs, 1.313 decisiones, 3.936 benchmarks y 129 intervenciones |
| Estado operativo | 265 jobs, 269 steps, 547 eventos auditables y 7 snapshots de equipo |
| Equipo autenticado | captura cold-start válida; 15 jugadores y estado de chips/FT vigente |
| Backup PostgreSQL | `/opt/orbital/backups/mova-fpl/postgres/20260823T193724Z` |
| Restore drill | restaurado en base temporal y eliminado al terminar |
| Backup integral | timer diario habilitado y corrida manual exitosa |
| Diagnóstico final | `18 PASS`, `0 WARN`, `0 FAIL` |
| Recursos | 5,5 GiB de memoria disponibles y 48 GiB libres en disco |

El import conserva artefactos SQLite inmutables con `quick_check`, hashes SHA-256 y manifiesto.
La réplica puede reconstruirse desde esos artefactos sin depender del estado mutable de origen.

## Hallazgos del rollout

1. El primer arranque detectó que el worker no podía leer el secreto PostgreSQL. El bootstrap
   quedó restringido a `root:10001` con modo `0640`: el host y el grupo del runtime pueden
   leerlo, pero no se volvió público.
2. La primera captura privada durante el build agotó `TimeoutStartSec` porque Compose todavía
   no encontraba la imagen final y comenzó a construirla. Con la imagen versionada disponible,
   el cold-start completó en 55 segundos.
3. El collector ahora espera `DOMContentLoaded` y el origen exacto de FPL, reintenta tres veces
   y valida schema más 15 picks. Un payload vacío o parcial nunca llega al ledger.

No se ejecutaron transferencias, chips ni escrituras browser durante el rollout.

## Gates conservados

- `writer=sqlite`;
- `postgres_role=shadow`;
- `mode=shadow`, `action_level=A0`;
- `kill_switch=true`, `browser_writes=false`;
- cero autorización nueva sobre la cuenta FPL.

## Estado del workpack

HV1-02a queda completo como fundación shadow. HV1-02 permanece abierto: el siguiente corte es
el repository adapter/dual-read y la acumulación de ciclos comparables antes de considerar
cualquier cambio de writer. El registro formal de releases de datasets/modelos también sigue
pendiente; los cuatro artefactos actuales están presentes y sanos, pero todavía no están
registrados en `model_releases`.
