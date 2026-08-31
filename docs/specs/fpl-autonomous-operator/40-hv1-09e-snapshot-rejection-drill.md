---
type: deployment-evidence
name: "HV1-09E — Snapshot rejection drill"
created: 2026-08-31
updated: 2026-08-31
tags: [mova, fpl, chaos, snapshot, integrity, path-traversal]
status: verified-live
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

## Evidencia verificada

- revisión productiva: `86dd286`;
- suite completa: `1116 passed, 1 skipped, 79 deselected`; pruebas dirigidas: 19 pass;
- Compose, `compileall` y `git diff --check`: pass;
- backup previo: job `job_65933d35ad284f52b8cdbb2efdbcf1f8`, ruta
  `/opt/orbital/backups/mova-fpl/20260831T021430Z`;
- rehearsal VPS: job `job_90085807b39b4d2ba478ed89705eead5`, diez de diez checks,
  `fixture_only=true`, `runtime_mutated=false`, output SHA-256
  `371086e254c977e3da0bcf517b6d094d59ce465c182e6093219e39b06e2e6b91`;
- replay: mismo job; identidad distinta: `conflict`, exit 2; failed replay cubierto por test;
- artifact real anterior y posterior al import: manifest pass, read parity pass, 54 tablas, cero
  fallos;
- import posterior `pgimport_e8db29355b9a43249b91047cfe26b524`: 54/54;
- `mova doctor`: 22 pass, 0 warn, 0 fail; watchdog activo; safety `safe_to_wait`;
- readiness: 12 pass, 6 pending, 0 blocked sobre 18;
  `SNAPSHOT_REJECTION_PROVEN=pass`, elegibilidad conservada en A0;
- backup posterior: job `job_cd4e60e92d0c458a8d240b7f94aeb175`, ruta
  `/opt/orbital/backups/mova-fpl/20260831T021639Z`.
