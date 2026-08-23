---
type: evidence
name: "HV1-02a — PostgreSQL shadow"
created: 2026-08-23
updated: 2026-08-23
tags: [mova, fpl, hv1-02, postgres, evidence]
status: implementation-validated
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

La integración local usó datos fixture descartables. La evidencia con el histórico real del
VPS se añade después del despliegue aprobado de la revisión versionada.

## Gates conservados

- `writer=sqlite`;
- `postgres_role=shadow`;
- `mode=shadow`, `action_level=A0`;
- `kill_switch=true`, `browser_writes=false`;
- cero autorización nueva sobre la cuenta FPL.
