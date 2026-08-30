---
type: evidence
name: "HV1-04/05 — Contexto estratégico e investigación aislada"
created: 2026-08-28
updated: 2026-08-30
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
| Revisión funcional certificada | `16b7085`; checkout, API y worker alineados por `mova doctor` |
| Pull requests del cierre | `#27`–`#37` |
| Runtime | `/opt/orbital/services/mova-fpl` |
| Migración SQLite ops | `006`; versiones aplicadas `1..6` |
| Imagen research | Node 22 por digest + Codex CLI `0.144.6` |
| Timer | `mova-fpl-research.timer`, habilitado y activo cada 15 min |
| Cadencia efectiva | ventana de 30 h, rutina cada 6 h y corrida final entre T-120/T-70 |
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

## Corridas reales de GW2

| Campo | Resultado |
| --- | --- |
| Research runs | `research_016a64c302e545d3a20b9dd3ad1a48ea` y `research_cac868ddf4cc4014b34a2740898e1441` |
| Provider | `codex_subscription`; uso registrado sin inventar costo USD |
| Estado final | `imported`, sin `error_code` residual |
| Documentos normalizados | 20 registros acumulados |
| Señales v2 | 26: 20 `accepted`, 6 `candidate`; existen 6 señales v1 legacy sin validation_status |
| Conflictos | 5: 2 no resueltos |
| Spool | inbox 0, outbox 0; request y resultado final archivados |
| Evidencia fallida | primer brief preservado en `quarantine`; eventos JSONL retenidos |

Los conflictos abiertos mantienen sus señales como candidatas. Ninguna confianza producida por
el modelo sustituye el gate: una señal solo es aceptada con fuente oficial o dos URLs distintas,
sin conflicto abierto y con TTL vigente.

## Conversión a servicio de noticias — 28 de agosto

El primer corte buscaba contexto de liga demasiado abierto y su intervalo de seis horas podía
perder la última ventana: la segunda corrida terminó a T-5h48 y la siguiente cadencia vencía
después del deadline. La revisión `16b7085` corrigió esa frontera sin introducir otro scraper:

- el collector FPL conserva `news`, status y chance oficial cada seis horas;
- `research_summary.focus` une la plantilla actual con hasta diez candidatos del batch baseline;
- nombres, clubes y posiciones se resuelven desde PostgreSQL y quedan dentro del hash del
  `CycleManifest`;
- señales activas previas entran al siguiente request para producir deltas y evitar repetición;
- una corrida final se exige entre T-120 y T-70 aunque no haya vencido la cadencia rutinaria;
- ticks sin request pendiente importan huérfanos y salen sin levantar Node/Codex;
- status y Prometheus conservan health global al abrir una nueva jornada.

El smoke vivo selló GW3 como `manifest_7fcd10d9001f41a2a7ac904413660faf`, revisión 1,
con 15/15 jugadores propios resueltos. Los candidatos son cero porque GW2 aún no comienza y no
existe un batch causal de GW3; el manifest lo declara `analytics_status=missing` en vez de usar
una proyección futura inventada. El timer fuera de ventana terminó en cuatro segundos con código
75 aceptado por systemd y sin crear contenedor research.

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
| Suite | `841 passed, 1 skipped, 79 deselected` |
| CI | verde en PR `#27`–`#37` |
| Doctor con red | 22 PASS, 0 WARN, 0 FAIL |
| Status | `healthy` |
| Fuentes | FPL, odds, WhoScored schedule y eventos `healthy` |
| Volumen vivo | 616 jugadores, 380 fixtures, 21 eventos de odds, 10 partidos/15.434 eventos WhoScored |
| Servicios analíticos | data y analytics `up=1` |
| Timers | siete timers activos y habilitados |
| API research | 2 runs imported, 20 documentos, 20 señales aceptadas, 2 conflictos abiertos |

## Cierre de memoria longitudinal HV1-04 — 30 de agosto

La revisión funcional `3367536`, desplegada en el VPS como `7c557f6`, añadió la migración SQLite
`014` y PostgreSQL `016`. `mova strategy prepare` selló para GW3 el manifest
`manifest_04be90ca521146618b0227580f211a3f`, revisión 14, con memoria
`mova-strategic-memory-v1` `ready/valid` y SHA-256
`08699a419c993fcacbb35b7b0fff8ae7665dd23704a26dbb7e8e5bc11d913496`.

La fotografía incluyó dos decisiones selladas —GW1 y GW2—, un review post-settlement de GW1 y
cero lecciones, porque todavía no existe ninguna promovida como `validated`. Verificó
`prior_gameweeks_only=true`, `validated_lessons_only=true` y `chat_history_allowed=false`; por
tanto, ninguna decisión de GW3 ni memoria conversacional entró al contexto. Strategist y Critic
reciben este mismo objeto desde el manifest inmutable.

El import shadow reconcilió 22/22 manifests y todas las tablas declaradas; `postgres verify`
quedó `pass`. Prometheus publicó memoria `ready=1`, dos decisiones, un review, cero lecciones y
plan revision 1. El backup auditado quedó en
`/opt/orbital/backups/mova-fpl/20260830T194020Z`. La suite local terminó con
`949 passed, 1 skipped, 79 deselected`; en vivo, doctor terminó 22 PASS, 0 WARN, 0 FAIL, siete
timers activos, cero unidades fallidas y el browser apagado. Los controles no cambiaron:
`shadow/A0`, `kill_switch=true`, `browser_writes=false`, compliance pendiente.

## Estado siguiente

HV1-04 queda cerrado: team state, plan versionado y memoria estratégica longitudinal forman un
contrato durable, acotado y observable. HV1-05 queda como servicio funcional en shadow,
focalizado y probado con un ciclo
real; permanece parcial hasta medir cobertura, precisión y costo a través de varios gameweeks.

El hardening `search → fetch independiente → locator/excerpt sellado` no está implementado: los
documentos actuales sellan metadata normalizada de las URLs citadas. Se mantiene como mejora
condicionada a evidencia multi-GW, no como infraestructura preventiva.

La siguiente iteración es HV1-06: Strategist + Critic + Validator y `DecisionEnvelope`, todavía
en shadow y sin autoridad de ejecución.
