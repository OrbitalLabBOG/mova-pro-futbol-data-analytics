---
type: deployment-evidence
name: "HV1-09H — Combined control-plane recovery drill"
created: 2026-08-31
updated: 2026-08-31
tags: [mova, fpl, chaos, combined-failure, recovery, idempotency]
status: verified-live
---

# HV1-09H — Combined control-plane recovery drill

## Objetivo

Demostrar que una caída simultánea de API, PostgreSQL shadow y browser no corrompe SQLite ni cambia
el equipo, y que los tres servicios recuperan su revisión aprobada. El escenario debía ser manual,
reversible, idempotente y restaurar el browser a su estado on-demand original.

## Contrato

`deploy/bin/combined-recovery-drill.sh ACTOR REASON IDEMPOTENCY_KEY` toma el lock exclusivo y todos
los locks de writers. Antes del corte valida API, paridad PostgreSQL, sesión browser, controles A0,
imágenes y fingerprints. Durante el corte exige los tres servicios indisponibles, ejecuta
`PRAGMA quick_check` sobre SQLite y comprueba que el snapshot persistido no cambió. Después recupera
PostgreSQL → API → browser, revalida paridad, sesión, revisiones y estado privado, borra los
payloads y restaura el browser apagado.

El importador allowlisted exige trece checks, downtime máximo de 240 s, revisión exacta,
fingerprints iguales y `fpl_state_mutated=false`. Readiness requiere ahora cuatro escenarios host:
API, PostgreSQL, browser y combinado.

## Hallazgo de idempotencia

La primera verificación de replay coincidió con el collector privado y devolvió 75 porque los
wrappers tomaban locks de servicios antes de consultar `host-status`. No inició otra caída. Se
corrigieron PostgreSQL, browser y combinado para resolver replay/conflict inmediatamente después
del lock exclusivo del drill. Tests fijan el orden; en producción el replay posterior devolvió el
mismo job y el cambio de identidad devolvió exit 2 sin detener servicios.

## Evidencia verificada

- revisión del outage: `f3e2c45`; revisión productiva final engine/browser: `49bf37b`;
- suite completa: `1137 passed, 1 skipped, 79 deselected`; pruebas dirigidas: 30 pass;
- Compose, `compileall`, `bash -n` y `git diff --check`: pass;
- backup previo: job `job_5b915ee2fe75438ca80909f2bd95cc44`, ruta
  `/opt/orbital/backups/mova-fpl/20260831T024943Z`;
- rehearsal VPS: job `job_8f4108555e6f4387be0efd3165897c0d`, trece de trece checks,
  downtime 19 s, artifact SHA-256
  `de8a81a14127dea44e05e63d463af8331d9a45763a58ee4272a78c971be9ca01`;
- fingerprint privado antes/después:
  `ac16f6e32bdd62c9e0f0e5a7b835c405996f886fe5dd30d4079c3524c144b111`;
- replay final: mismo job, exit 0; identidad distinta: `conflict`, exit 2;
- PostgreSQL posterior `pgimport_d1e96f7f66f34402a03764366326672a`: 54/54 y paridad pass;
- readiness: host recovery 4/4, total 13 pass, 6 pending, 0 blocked sobre 19;
- doctor final: 22 pass, 0 warn, 0 fail; checkout/imagen `49bf37b`;
- safety `safe_to_wait`; controles `shadow/A0` intactos;
- browser final: imagen `49bf37b`, `Exited (0)`, noVNC detenido;
- backup posterior: job `job_0005ae50cc3e4804a9774051dde9bda3`, ruta
  `/opt/orbital/backups/mova-fpl/20260831T025240Z`.

## Límites

No se reinició el kernel ni el VPS. El escenario no sustituye un reboot/restore completo, no
prueba un commit real en FPL y no cuenta como rehearsal multi-GW de los drivers. Alertas externas
y backups off-host siguen requiriendo destinos y autoridad explícitos.
