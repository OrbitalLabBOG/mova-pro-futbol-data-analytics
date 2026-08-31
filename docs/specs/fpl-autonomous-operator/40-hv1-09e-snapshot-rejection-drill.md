---
type: deployment-evidence
name: "HV1-09E — Snapshot rejection drill"
created: 2026-08-31
updated: 2026-08-31
tags: [mova, fpl, chaos, snapshot, integrity, path-traversal]
status: implemented-pending-live-rollout
---

# HV1-09E — Snapshot rejection drill

## Objetivo

Demostrar que el boundary PostgreSQL rechaza snapshots alterados, corruptos o con referencias de
archivo inseguras antes de leerlos o compararlos. El rehearsal debe ser hermético: sólo opera
sobre SQLite mínimos en un directorio temporal y no conecta PostgreSQL ni toca datos vivos.

## Hardening

`_verify_manifest` exige ahora:

- SHA-256 esperado y manifest sellado;
- schema exacto `mova-postgres-import-source-v1` y tres fuentes exactas;
- entradas con `name`, `bytes` y `sha256` tipados;
- nombres basename, únicos y contenidos en el artifact root;
- archivos regulares, no symlinks, con tamaño, hash y `quick_check` correctos.

El orden de checks evita seguir un symlink incluso para resolverlo. Ningún path del manifest se
abre hasta superar las validaciones léxicas y de tipo de archivo.

## Drill y evidencia

`mova drill snapshot --actor ... --reason ... --idempotency-key ...` crea un job auditado y
prueba diez invariantes:

1. baseline válido aceptado;
2. checksum del manifest alterado rechazado;
3. contrato/schema del manifest inválido rechazado;
4. checksum de DB alterado rechazado;
5. DB no-SQLite rechazada;
6. tamaño declarado incorrecto rechazado;
7. nombre duplicado rechazado;
8. path traversal rechazado;
9. symlink rechazado;
10. workspace temporal eliminado.

La salida declara `fixture_only=true` y `runtime_mutated=false`. La identidad liga escenario,
actor, razón y clave. Un replay completado reutiliza el job; un cambio de identidad devuelve
`conflict`; un job fallido nunca reaparece como éxito. Readiness exige este job mediante
`SNAPSHOT_REJECTION_PROVEN` para A1+.

## Límites

Este escenario prueba el boundary de evidencia sin dañar un artifact real. No sustituye la caída
real PostgreSQL ya cubierta, ni prueba browser/DOM, save ambiguo, fallos combinados o reboot.

## Evidencia previa al rollout

- pruebas dirigidas: contrato, diez checks, ledger, replay, conflicto y failed replay;
- suite completa, smoke Docker y evidencia VPS se anexarán después del commit candidato;
- `compileall` y `git diff --check`: pass.

