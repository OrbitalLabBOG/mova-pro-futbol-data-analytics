---
type: deployment-evidence
name: "HV1-09F — Browser failure drill"
created: 2026-08-31
updated: 2026-08-31
tags: [mova, fpl, browser, dom, ambiguous-save, apply-once]
status: verified-live
---

# HV1-09F — Browser failure drill

## Objetivo

Demostrar de forma repetible que el executor falla cerrado cuando deriva el DOM, cambia el estado
privado observado antes de escribir o el GET post-reload no confirma el resultado. El rehearsal
debía registrar evidencia en el ledger vivo sin abrir el browser, tocar FPL ni cambiar controles.

## Hallazgo y hardening

El lifecycle ya convertía un mismatch post-reload en `ambiguous`, abría P0 y prohibía retry. La
auditoría encontró que `begin()` revalidaba el snapshot persistido y los gates mutables, pero no
comparaba explícitamente el fingerprint del pre-state recibido en esa llamada con el autorizado.
Ahora agrega `OBSERVED_PRE_STATE_CHANGED` y termina `blocked` antes de `applying`.

## Contrato del drill

`mova drill browser-failure --actor ... --reason ... --idempotency-key ...` crea dos control
planes temporales y prueba once invariantes:

1. contrato DOM válido aceptado;
2. versión DOM distinta rechazada;
3. orden DOM distinto al GET rechazado;
4. control accesible requerido ausente rechazado;
5. número distinto de controles `Switch player` rechazado;
6. mismatch post-reload clasificado `ambiguous`;
7. save ambiguo abre P0;
8. intento ambiguo no puede reclamarse de nuevo;
9. pre-state nuevo bloquea antes de `applying`;
10. intento bloqueado nunca entra a aplicación;
11. workspace temporal eliminado.

La salida exige `fixture_only=true` y `runtime_mutated=false`. La identidad liga escenario,
actor, razón y clave; replay completado reutiliza el job, identidad distinta devuelve `conflict`
y un job fallido nunca reaparece como éxito. Readiness incorpora
`BROWSER_FAILURE_DRILL_PROVEN` para A1+.

## Evidencia verificada

- revisión productiva, checkout e imagen: `b05a777`;
- suite completa: `1126 passed, 1 skipped, 79 deselected`; pruebas dirigidas: 27 pass;
- Compose, `compileall` y `git diff --check`: pass;
- backup previo: job `job_f3b019a9e90c41318eca80154b0ebe08`, ruta
  `/opt/orbital/backups/mova-fpl/20260831T022509Z`;
- rehearsal VPS: job `job_75fe15359b524febbac82b8a332a6214`, once de once checks,
  output SHA-256 `160878d043833826647e90a2292805fb569f76ec1f94151f598758781dc4a2f3`;
- replay: mismo job; identidad distinta: `conflict`, exit 2; failed replay cubierto por test;
- import PostgreSQL posterior `pgimport_d2d63bdbb53a4fcc8bbd022481dfd75c`: 54/54 y paridad
  de contenido `pass`;
- readiness: 13 pass, 6 pending, 0 blocked sobre 19;
  `BROWSER_FAILURE_DRILL_PROVEN=pass`, elegibilidad conservada en A0;
- `mova doctor`: 22 pass, 0 warn, 0 fail; `mova safety`: `safe_to_wait`;
- controles intactos: `shadow/A0`, kill switch encendido, browser writes apagado y compliance
  pendiente;
- backup posterior: job `job_d746882815974c5ea7704972405e8535`, ruta
  `/opt/orbital/backups/mova-fpl/20260831T022700Z`.

## Límites

El escenario prueba los contratos y la máquina de estados con adapters desechables. No simula una
caída real del contenedor browser, no cuenta como rehearsal vivo por gameweek y no cubre fallos
combinados ni reboot. Ninguna evidencia de este documento promueve autoridad.
