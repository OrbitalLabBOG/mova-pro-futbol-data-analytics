---
type: deployment-evidence
name: "HV1-09G — Browser recovery drill"
created: 2026-08-31
updated: 2026-08-31
tags: [mova, fpl, browser, recovery, session, host-drill]
status: verified-live
---

# HV1-09G — Browser recovery drill

## Objetivo

Probar una caída real del contenedor Chromium/noVNC y recuperar la misma sesión autenticada sin
mutar FPL, exponer estado privado ni dejar el servicio permanentemente encendido. La evidencia
debía entrar por el importador host allowlisted y ampliar el gate de recuperación existente.

## Diseño

`deploy/bin/browser-recovery-drill.sh ACTOR REASON IDEMPOTENCY_KEY`:

- toma locks exclusivos del drill y del collector privado;
- exige exactamente `shadow/A0`, kill switch activo, compliance pendiente y writes apagados;
- conserva el estado inicial `running/exited` y lo restaura mediante trap;
- levanta browser, valida noVNC/CDP y realiza un GET autenticado read-only;
- guarda los payloads sólo en un directorio `0700` bajo `/run`;
- detiene realmente el contenedor y exige indisponibilidad;
- recupera la misma imagen y perfil, repite el GET y compara el fingerprint normalizado;
- borra los payloads antes de importar evidencia y deja únicamente hashes/checks sanitizados.

El contrato host `browser_recovery` exige nueve checks, downtime máximo de 180 s, revisión exacta,
fingerprints iguales y `fpl_state_mutated=false`. Replay idéntico no reinicia el servicio;
identidad distinta falla con exit 2. `HOST_RECOVERY_DRILLS_PROVEN` requiere ahora los escenarios
API, PostgreSQL y browser.

## Evidencia verificada

- revisión productiva, engine y browser: `e722da8`;
- suite completa: `1132 passed, 1 skipped, 79 deselected`; pruebas dirigidas: 29 pass;
- Compose, `compileall`, `bash -n` y `git diff --check`: pass;
- backup previo: job `job_fd44d4cea5184b4aba8c90acc5a14f80`, ruta
  `/opt/orbital/backups/mova-fpl/20260831T024105Z`;
- rehearsal VPS: job `job_4319c2e5875749258bd601438e98de3b`, nueve de nueve checks,
  downtime 10 s, artifact SHA-256
  `9aa1643ae88c57feb22e02cd6fffe40f21154b33c7fc0051aa0e73aa968055ad`;
- fingerprint privado antes/después:
  `ac16f6e32bdd62c9e0f0e5a7b835c405996f886fe5dd30d4079c3524c144b111`;
- replay: mismo job sin segunda caída; identidad distinta: `conflict`, exit 2;
- PostgreSQL posterior `pgimport_2c21492c656f41848e60103ea7a0897c`: 54/54 y paridad pass;
- readiness: host recovery 3/3, total 13 pass, 6 pending, 0 blocked sobre 19;
- doctor: 22 pass, 0 warn, 0 fail; safety `safe_to_wait`;
- browser final: imagen `e722da8`, estado `Exited (0)`, noVNC detenido como al inicio;
- backup posterior: job `job_6b752a32e1c448c2a0abf46440af1daf`, ruta
  `/opt/orbital/backups/mova-fpl/20260831T024357Z`.

## Límites

El drill prueba recuperación aislada del browser. No cubre una caída combinada con API/DB, reboot
del VPS ni un commit real en FPL. Tampoco cuenta como rehearsal vivo de captaincy, lineup o R3 y
no promueve niveles de autonomía.
