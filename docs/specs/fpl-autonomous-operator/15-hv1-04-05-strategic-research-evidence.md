---
type: evidence
name: "HV1-04/05 — Contexto estratégico e investigación aislada"
created: 2026-08-28
updated: 2026-08-28
tags: [mova, fpl, hv1-04, hv1-05, strategy, research, codex, vps]
status: deployed-shadow
---

# Evidencia HV1-04/05 — Contexto estratégico e investigación aislada

## Alcance cerrado

Este corte conecta plan de temporada, estado privado del equipo, fuentes vigentes,
proyección aprobada e investigación web en un `CycleManifest` sellado. El worker Codex es
one-shot y solo puede leer requests del spool, buscar en web y producir JSON estructurado.
Un importador determinista decide qué entra en las tablas operativas.

El corte no implementa todavía Strategist/Critic/Validator ni autoriza transferencias,
capitanía, chips o escrituras en FPL. Supabase conserva únicamente seguimiento PM.

## Release y runtime

| Campo | Evidencia verificada |
| --- | --- |
| Revisión funcional certificada | `c26286298893bf6e3370293d4ff39952b8f7f658`; el SHA de checkout/imagen posterior debe validarse con `mova doctor` |
| Pull requests del cierre | `#27`–`#37` |
| Runtime | `/opt/orbital/services/mova-fpl` |
| Migración SQLite ops | `006`; versiones aplicadas `1..6` |
| Imagen research | Node 22 por digest + Codex CLI `0.144.6` |
| Timer | `mova-fpl-research.timer`, habilitado y activo cada 15 min |
| Cadencia efectiva | ventana de 30 h y máximo una corrida cada 6 h |
| API | `/api/v1/strategy`, tablas research read-only y métricas Prometheus |

## Contexto sellado de GW2

| Campo | Valor |
| --- | --- |
| Cycle | `2026-27-gw02` |
| Deadline | `2026-08-28T17:30:00Z` |
| Season plan | `plan_9b385f26cf7445b9833ee04ed2b72364`, revisión 1 |
| CycleManifest | `manifest_ae1f85989aad4208b0212308b420dcaf`, revisión 5 |
| Team state | válido, 15 jugadores, 1 FT, banco 0, poderes disponibles observados |
| Analytics batch | `projection_bf7fe3192a5a43d3a41f6f71ab13c260`, baseline aprobado |
| Modelos | minutes `1.1.0`, points `1.1.0`, 616 jugadores |

El plan conserva horizonte GW2–GW8, máximo cero hits por defecto y exige caso explícito para
chips. No contiene una decisión de jugador o poder para GW2.

## Primera corrida real

| Campo | Resultado |
| --- | --- |
| Research run | `research_016a64c302e545d3a20b9dd3ad1a48ea` |
| Provider | `codex_subscription`; uso registrado sin inventar costo USD |
| Estado final | `imported`, sin `error_code` residual |
| Documentos | 13 |
| Señales | 16: 14 `accepted`, 2 `candidate` |
| Conflictos | 4: 1 no resuelto |
| Spool | inbox 0, outbox 0; request y resultado final archivados |
| Evidencia fallida | primer brief preservado en `quarantine`; eventos JSONL retenidos |

El único conflicto abierto mantiene su señal como candidata. Ninguna confianza producida por
el modelo sustituye el gate: una señal solo es aceptada con fuente oficial o dos URLs distintas,
sin conflicto abierto y con TTL vigente.

## Hallazgos del ejercicio real

La certificación encontró y corrigió cuatro gaps que las pruebas con fixtures no mostraban:

1. la imagen slim carecía de `ca-certificates` para HTTPS/WSS;
2. `const` y `enum` necesitaban `type` explícito para Structured Outputs;
3. fuentes oficiales pueden publicar solo `YYYY-MM-DD`, normalizado ahora a medianoche UTC;
4. cada conflicto, además de cada señal, debe citar únicamente URLs inventariadas.

También se corrigieron lifecycle y observabilidad: paths canónicos apuntan a `archive`, los
requests consumidos salen del inbox, un retry exitoso limpia errores anteriores y el doctor
acepta la equivalencia entre SHA corto de checkout y SHA completo de imagen.

## Seguridad y autoridad

- contenedor sin repo, bases, modelos, perfil browser, password PostgreSQL ni key de odds;
- root filesystem read-only, capabilities removidas y usuario no root `10002`;
- shell, Computer Use, browser, apps y multi-agent deshabilitados en Codex;
- auth persistente con permisos `0700/0600`, nunca impreso ni copiado a Git/Supabase;
- controles finales: `mode=shadow`, `action_level=A0`, `kill_switch=true`,
  `browser_writes=false`, `compliance_gate=pending`.

## Verificación final

| Check | Resultado |
| --- | --- |
| Suite | `830 passed, 1 skipped, 79 deselected` |
| CI | verde en PR `#27`–`#37` |
| Doctor con red | 22 PASS, 0 WARN, 0 FAIL |
| Status | `healthy` |
| Fuentes | FPL, odds, WhoScored schedule y eventos `healthy` |
| Volumen vivo | 616 jugadores, 380 fixtures, 21 eventos de odds, 10 partidos/15.434 eventos WhoScored |
| Servicios analíticos | data y analytics `up=1` |
| Timers | siete timers activos y habilitados |
| API research | 1 run imported, 14 señales aceptadas, 1 conflicto abierto |

## Estado siguiente

HV1-04 queda parcial: plan, team state y manifest están operativos; falta memoria longitudinal
de estrategia. HV1-05 queda funcional en shadow y probado con un ciclo real; permanece parcial
hasta medir cobertura, precisión y costo a través de varios gameweeks.

La siguiente iteración es HV1-06: Strategist + Critic + Validator y `DecisionEnvelope`, todavía
en shadow y sin autoridad de ejecución.
