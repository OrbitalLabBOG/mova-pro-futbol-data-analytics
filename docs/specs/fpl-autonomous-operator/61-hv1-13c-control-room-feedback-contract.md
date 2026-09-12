---
type: rollout
name: "HV1-13C — control room, costo y feedback observable"
created: 2026-09-12
updated: 2026-09-12
tags: [mova, fpl, harness, observability, dr, costs, models, feedback]
status: deployed_verified
---

# HV1-13C — control room, costo y feedback observable

## Problema

El cockpit mostraba salud, autoridad, workflow y presupuesto agregado, pero un operador debía
consultar contratos separados para responder qué modelos estaban activos, cuánto consumo llevaba
cada proveedor/modelo, qué evidencia DR seguía pendiente y si el loop de feedback había producido
scorecards, evaluaciones o lecciones. Esa fragmentación dificultaba operar el runtime desde ORBIX
y podía ocultar la diferencia entre una plataforma sana y una promoción técnicamente elegible.

## Contrato implementado

`mova cockpit --json` conserva `schema=mova-cockpit-v1` y añade campos compatibles:

- `models`: bundle predictivo activo, último batch/scorecard, conteos de drift y routing
  Researcher/Strategist/Critic;
- `economics`: consumo all-time, por mes y por proveedor/modelo, modo de facturación y señal
  explícita de costo USD conocido;
- `feedback`: reconciliación automática después de `data_checked`, review causal automático
  después de un closeout verificado y estado de propuestas/evaluaciones/lecciones;
- `resilience`: resumen directo de los gates de recovery, corrupción, browser, PostgreSQL,
  backup/restore off-host y alertas externas;
- `exit_shadow`: nivel vigente, nivel técnicamente elegible, blockers y siguientes acciones del
  scorecard canónico.

`mova doctor --json` adjunta el mismo resumen en `observability`. El doctor no duplica datos ni
autoridad y sigue funcionando cuando el control room no puede construirse.

El API reutiliza el snapshot analítico ya publicado por el worker y resuelve el bundle desde los
controles/artefactos locales. No recibe el secreto owner de PostgreSQL para construir esta vista.

Prometheus publica gates de readiness por código, evidencia del loop de aprendizaje, tokens,
conocimiento del costo USD y número de releases. Las etiquetas son finitas y no incluyen GW,
IDs, paths, prompts o secretos.

## Semántica de costo

Las ejecuciones actuales de agentes usan `codex_subscription`. El ledger registra llamadas,
tokens y modelo, pero no recibe una tarifa marginal contractual. Por eso
`estimated_cost_usd=null`, `unknown_cost_uses>0` y `cost_known=false` son el resultado correcto.
Una estimación USD sólo puede aparecer cuando el proveedor entregue costo o exista una política
de imputación aprobada y versionada.

## Feedback y promoción

El timer analítico ya reconcilia automáticamente cada batch causal al aparecer el settlement
oficial `data_checked`. El review causal se dispara automáticamente cuando existe además un
closeout de decisión/equipo verificado. Aceptar una propuesta genera memoria, pero nunca cambia el
modelo activo: la promoción continúa en el release gate explícito.

Esta iteración no cambia `shadow/A0`, compliance, kill switch, browser writes ni entrypoints. La
salida de shadow exige evidencia longitudinal real, canal externo y restore off-host. El control
room muestra esos faltantes; no los da por cumplidos.

## Verificación requerida

1. pruebas de contrato de cockpit, scorecard y configuración;
2. suite completa `pytest -q`;
3. build de imagen con SHA inmutable y migraciones sin drift;
4. `mova doctor --json`, `mova cockpit --json`, `/metrics` y healthchecks en el VPS;
5. comprobar que el runtime continúa `shadow/A0`, kill switch activo y browser writes apagado;
6. registrar revisión, rollback e imagen desplegada después de observar el runtime.

## Rollback

Volver a la imagen anterior restaura la forma previa del cockpit. Los campos añadidos son
read-only y no requieren migración de datos. Los consumidores de v1 deben tolerar campos
adicionales y no inferir autoridad por su presencia.

## Evidencia de despliegue

Verificado el **12 de septiembre de 2026 a las 17:25 UTC** sobre
`191d809fd3745c0fb8bb24a4e35e3b2f45902413`:

- CI de los PR [#157](https://github.com/OrbitalLabBOG/mova-pro-futbol-data-analytics/pull/157),
  [#158](https://github.com/OrbitalLabBOG/mova-pro-futbol-data-analytics/pull/158) y
  [#159](https://github.com/OrbitalLabBOG/mova-pro-futbol-data-analytics/pull/159) pasó;
- suite local: 1.731 pruebas pasaron y 79 quedaron excluidas por markers;
- API `/api/v1/cockpit`: HTTP 200, `schema=mova-cockpit-v1`;
- doctor: 24 PASS, 0 WARN, 0 FAIL; checkout e imagen coinciden;
- dashboard público: HTTP 200; `/api/v1/cockpit` público: HTTP 404;
- Prometheus expone gates, learning, tokens, releases y `agent_cost_known`;
- baseline GW5 `projection_2457f5d8bb44450e8123fd8b0cf9115c` aprobado, bundle
  minutes/points 1.1.0 y cero alertas de drift;
- controles posteriores: `shadow/A0`, kill switch activo, browser writes apagado y promoción
  automática deshabilitada.

El rollback operativo conserva la imagen anterior y el backup
`/etc/mova-fpl/deploy.env.pre-control-room`; restaurarlos requiere actualizar checkout e imagen
como una pareja y volver a ejecutar doctor. No fue necesario usar rollback.
