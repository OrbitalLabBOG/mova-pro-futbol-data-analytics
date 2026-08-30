---
type: evidence
name: "MOVA FPL — rollout HV1-07C apply-once"
created: 2026-08-30
updated: 2026-08-30
tags: [mova, fpl, autonomy, executor, verifier, idempotency, rollout]
status: verified
---

# Rollout HV1-07C: apply-once state machine + verifier

## Resultado

El 30 de agosto de 2026 se desplegó la frontera durable del executor sin ampliar autoridad. La
revisión productiva del VPS quedó en `e46b31c`; checkout e imagen engine coincidieron. La imagen
browser del mismo tag quedó construida, pero el perfil permaneció detenido y Compose conservó
`MOVA_ENABLE_BROWSER_WRITES=0`.

Los controles efectivos no cambiaron:

```text
mode=shadow · action_level=A0 · compliance=pending
kill_switch=true · browser_writes=false
```

SQLite aplicó migration 010. PostgreSQL shadow aplicó migration 012. El backup anterior al
rollout quedó en `/opt/orbital/backups/mova-fpl/20260830T163106Z`; el backup PostgreSQL se selló
en el mismo corte. Las migraciones son aditivas y la imagen previa `04ca113` sigue disponible para
rollback.

## Qué quedó construido

- ledger `execution_attempts` con una reserva única por plan e idempotency key;
- eventos append-only para `prepared → claimed → applying → terminal`;
- token opaco entregado una vez y almacenado sólo como SHA-256;
- lease entre 30 y 600 segundos y compare-and-swap transaccional;
- revalidación de deadline, estado privado, P0/P1 y controles en `prepare`, `claim` y `begin`;
- command bundle inmutable R2 con hash físico y de contenido;
- límite explícito de write ambiguity al entrar a `applying`;
- verifier contra GET privado posterior al reload, incluido timestamp posterior al apply;
- terminal `ambiguous`, P0 y prohibición de retry ante mismatch;
- CLI con token exclusivamente por stdin, API read-only y métricas Prometheus;
- mirror SQLite → PostgreSQL para intentos y eventos;
- preflight orquestado automáticamente por el tick después de cada envelope.

El API omite `claim_token_sha256`; los artifacts de evidencia no contienen el estado privado, sólo
fingerprints, checks y hashes.

## Evidencia hermética

- suite completa: `894 passed, 1 skipped, 79 deselected`;
- compileall del paquete: aprobado;
- `docker compose config`: aprobado;
- dos llamadas `prepare` con la misma clave retornan un intento;
- un segundo `claim` no entrega token;
- un cambio de kill switch antes de claim o después de claim bloquea antes de `applying`;
- modificar un byte del command bundle impide reclamarlo;
- un post-read exacto termina `verified`;
- un post-read distinto termina `ambiguous` y abre P0;
- el DOM fixture basado en la UI viva exige sesión, deadline, cuatro chips y 15 controles
  `Switch player`.

## Rehearsal productivo sin writes

El tick forzado auditado `force:hv1-07c:e46b31c` completó fuentes, manifest, modelo, envelope y
preflight. La propuesta vigente fue R3 con wildcard y produjo:

- envelope `envelope_790a11c2e1b942b1184d622c`;
- plan `execplan_734affe09d79fde62cd0592c`;
- content SHA-256 `734affe09d79fde62cd0592c67aef1397a1a910e9936233e5e697926547313ba`;
- preflight automático en 55 ms;
- estado final `blocked` con ocho blockers;
- cero execution attempts, claims, leases o sesiones browser.

Los blockers fueron `ENVELOPE_STAGED`, `EXECUTION_WINDOW`, `NO_OPEN_P0_P1`, `KILL_SWITCH_OFF`,
`BROWSER_WRITES_ENABLED`, `COMPLIANCE_APPROVED`, `AUTONOMY_LEVEL_SUFFICIENT` y
`AUTONOMOUS_MODE`. Esto coincide con la política A0 y el incidente P1 histórico todavía abierto.

El import final PostgreSQL posterior al rehearsal fue
`pgimport_70f7499c8d604d4b9eea47c0f3b69ae4`. La verificación final reconcilió:

| Tabla | SQLite | PostgreSQL | Estado |
| --- | ---: | ---: | --- |
| execution plans | 2 | 2 | pass |
| preflight checks | 32 | 32 | pass |
| execution attempts | 0 | 0 | pass |
| attempt events | 0 | 0 | pass |

`mova doctor --json` terminó con 22 PASS, 0 WARN y 0 FAIL. API, timers, PostgreSQL privado,
collector y analytics permanecieron sanos. El estado consolidado puede seguir mostrando
`critical` por el P1 histórico; no se resolvió silenciosamente porque requiere su lifecycle y
evidencia propios.

## Límite y siguiente gate

Este corte no hace clicks. El módulo compila intención determinista R2, pero falta el driver host
que consuma el bundle, opere los nombres accesibles y mantenga el token únicamente en memoria.
R3 —transfers, hits y chips— falla cerrado incluso si un plan futuro quedara autorizado.

Antes de promover R2 se requieren tres rehearsals supervisados completos con pre-read, commit
único, reload, post-read exacto, evidencia íntegra y cero duplicados. Sólo después se podrá elevar
la clase R2 mediante controles versionados. A3/R3 exige además su propio adapter, contratos de
modales de hit/chip y rehearsals independientes.
