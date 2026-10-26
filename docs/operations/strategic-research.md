---
type: runbook
name: "MOVA FPL — contexto estratégico e investigación"
created: 2026-08-27
updated: 2026-10-22
tags: [mova, fpl, strategy, research, codex, evidence]
status: active
---

# Contexto estratégico e investigación

## Campaña prospectiva v2 — 23 de octubre

[ADR-019](../specs/fpl-autonomous-operator/decisions/ADR-019-weekly-continuity-campaign-acceptance.md)
añade aceptación opt-in por campaña completa. `mova strategy acceptance contract
--campaign` emite el contrato; registrar exige un manifest v2 aprobado con tres
GWs futuras no inferidas ni ya inscritas. v1 y cohortes fallidas no cambian.
Todas las corridas cuentan: parcial válido queda pending hasta cutoff; cualquier
fallo/consumo incierto sigue bloqueando. Exige broad/refresh/final, 90% procesado,
80% evidencia y cero conflictos a tiempo. No promueve A3 ni aumenta cuotas.
Las continuaciones envían pistas sólo de pendientes, sin cuerpos duplicados;
el original queda sellado y cada fuente reutilizada debe verificarse de nuevo.

## Qué resuelve

Esta vertical conecta el estado real del ciclo con investigación web sin conceder autoridad
operativa al LLM:

~~~text
plan versionado
  + decisiones/reviews previos + lecciones validadas
  → memoria estratégica longitudinal sellada
  → CycleManifest sellado
  → foco: plantilla + candidatos xP + notas oficiales FPL
  → request JSON sin secretos
  → Codex web search aislado
  → brief candidato + coverage explícita
  → fetch HTTPS independiente y excerpt/locator sellado
  → validación determinista
  → documentos, señales, conflictos, cobertura, utilidad y costo/uso
~~~

SQLite ops.db continúa como writer oficial hasta el cutover de HV1-02. PostgreSQL conserva
datos y analítica; Supabase es solamente PM. Ninguna señal modifica predicciones, decisiones o
el equipo por sí sola.

El servicio tiene dos capas complementarias. El collector FPL conserva cada seis horas el
campo oficial `news`, `status` y `chance_of_playing_next_round`; el worker Codex hace
investigación web profunda únicamente en ventanas de decisión. No existe un scraper de prensa
residente ni una llamada LLM por tick.

## Contrato vigente y antecedentes

Al abrir un refresh T−6h/T−2h, un bloqueo de continuación por cuota,
cutoff o integridad del padre conserva su motivo y pendientes. El scheduler no
puede convertirlo en una investigación nueva para eludir la admisión. Una
reserva de 500k no sustituye el margen de un job completo que exige la
continuación; sin ese margen el refresh queda bloqueado y la cobertura anterior
se conserva, sin declarar fuentes frescas ni ampliar cuotas automáticamente.

Researcher activo 1.17: registry `agent_releases.json`, app-server, modelo
`gpt-6-astra`/medium; el contrato sellado y routing vivo prevalecen sobre defaults.
La continuación trabaja IDs pendientes, sin reabrir radar global por rutina.
La política vigente es `research-claim-2026.09.5`; los requests antiguos conservan
su política inmutable. Las secciones fechadas explican antecedentes, no overrides.
Ver [continuación autónoma](#continuación-autónoma-de-pendientes-1170) y ADR-016.

### Antecedente — contexto y alcance trazables (22 de septiembre)

El worker conserva íntegro el request sellado y añade `acquisition_plan` al contexto
entregado a Researcher. Agrupa sujetos únicos por club, calcula el objetivo 90% y
expone una estimación condicional de documentos necesarios. Supone una fuente reciente
que nombre a todos los sujetos de cada club; fuentes multiclub pueden superar esa
estimación. No es evidencia ni modifica budgets. Clubes desconocidos no se agrupan.
Plan, plantilla, proyecciones, catálogo global, alertas, memoria y antecedentes siguen
presentes. El catálogo real ya está compacto: no se anuncia ahorro de tokens.

Cada intento autorizado conserva `logs/<run>.<attempt>.context.json`: hash de la vista
realmente enviada, hash del request original, bytes de JSON/prompt y contadores de
sujetos, catálogo, antecedentes y hints. Es diagnóstico; no cambia el receipt contable
ni acredita búsquedas, calidad o cobertura. El importador sigue validando el request
original y recuperando fuentes independientemente. La validación interactiva durante
el turno sigue pendiente; no se añadió una tool MCP en esta entrega.

El gate longitudinal evalúa la última corrida importada de **cada ciclo de todo el
historial**, independientemente del `limit` de presentación. Conserva mínimo tres GWs,
90/80 y cero conflictos en todas las medidas. Empates se ordenan por importación,
encolado e ID. Reintentos no deben ocultar GWs fallidas. Esto corrige paginación, no
introduce una ventana de tres GWs recientes ni reetiqueta resultados históricos.

### Antecedente — refactor de contexto y calidad en A0/shadow

El checkout actual prepara `research_summary.plan` con horizonte, supuestos, ventanas de chips y
guardrails del plan activo. `research_summary.world` añade el catálogo oficial de IDs,
fixtures de las cinco próximas GWs y hasta 80 alertas de cambios en status/chance/news
entre snapshots FPL; declara `alerts_total` y `alerts_truncated`. La consulta se limita
al `as_of_at` sellado. Las proyecciones de los 15 propios se resuelven por ID del batch,
aunque no aparezcan en su top-N. Las señales aceptadas de las tres GWs anteriores son
pistas históricas, no evidencia heredada. Si PostgreSQL no está disponible, `world.status`
es `missing` o `degraded` y no se inventa catálogo global.

El mismo worker dedica una exploración acotada a lesiones y cambios de rol en toda la liga;
el resto sigue priorizando plantilla y candidatos. El importador aplica la política
`research-claim-2026.09.2` a requests nuevos con catálogo: exige ID conocido, nombre
explícito en el excerpt, vocabulario del tema, fecha declarada que aparece en la página y fetch anterior al
deadline para `accepted`; dos fuentes no oficiales deben pertenecer a hosts distintos.
La misma fuente debe respaldar sujeto, tema y fecha vigente: 3 días para disponibilidad,
lesión, suspensión o minutos; 7 para rol, balón parado y contexto; 30 para fichajes.
La cobertura actual también exige publicación de los últimos 7 días. Requests ya
sellados con `2026.09.1` conservan su contrato anterior.
Si no puede demostrarlo, conserva la señal como `candidate`
y registra la razón; una página genérica deja `not_checked` en cobertura. Esta es una
comprobación conservadora de identidad/tema, **no** una prueba completa de que cada matiz
del claim sea verdadero. El replay etiquetado y la revisión de casos difíciles siguen
siendo necesarios antes de afirmar calidad causal.

La telemetría nueva está en `coverage.quality` y
`mova_research_quality{measure=...}`: tamaño de catálogo, alertas, señales dentro/fuera
del foco y señales degradadas por calidad. `search_requests` permanece `null`: Codex
native search no expone al host un contador exigible. El límite del prompt orienta al
agente; el enforcement real es timeout, autorización previa del presupuesto y límites
de salida. Codex CLI reporta tokens solo al terminar: el límite por job **no** corta
una llamada física al llegar a ese número. Un overrun se liquida con tokens reales y
exige revisión durable. El worker desactiva plugins del host para reducir contexto
ajeno al request; el ahorro real sigue pendiente de medición.
No interpretar `search_requests=null` como cero consultas. El gate 90/80 vigente no
cambia y los runs v1/v2 anteriores no se reetiquetan.

Desde el corte del 14 de septiembre el prompt opera `coverage-first`: agrupa el foco por club,
busca primero partes, convocatorias o alineaciones oficiales que nombren a varios sujetos y sólo
después extrae deltas materiales. El objetivo sigue siendo cobertura ≥ 90 % y evidencia verificada
≥ 80 %; no se redujo el gate. Una misma URL puede acreditar varios jugadores únicamente cuando el
fragmento literal los contiene de forma inequívoca. El request sella un `scope_policy`
decreciente: la corrida amplia admite 8 búsquedas/10 documentos, el refresco 5/8 y la final
4/6. Refresh y final son `delta_only`; no vuelven a investigar narrativa sin un cambio material.
El worker evita búsquedas individuales de jugadores sin alerta y conserva `not_checked` cuando
el presupuesto no alcanza. La efectividad se valida en corridas posteriores;
el cambio de prompt por sí solo no cuenta como una GW passing ni resuelve el overrun histórico.

El routing del worker separa costo y juicio: Researcher usa `gpt-5.6-luna` con
`reasoning_effort=medium`; la deliberación conjunta Strategist/Critic usa `gpt-5.6-terra` con
`reasoning_effort=high`. Se configura con `MOVA_RESEARCH_MODEL`,
`MOVA_RESEARCH_REASONING_EFFORT`, `MOVA_DELIBERATION_MODEL` y
`MOVA_DELIBERATION_REASONING_EFFORT`. El worker pasa modelo y esfuerzo explícitamente a Codex,
ignora la configuración personal y registra en cada resultado/receipt el modelo realmente usado.
No existe fallback implícito ni `OPENAI_API_KEY`: la autenticación es la suscripción Codex montada.

## Contratos

- season_plans: horizonte, supuestos, ventanas de chips y guardrails, por revisión.
- cycle_manifests: fuentes, team state, proyección, plan, memoria estratégica y research observados.
- research_runs: request/result, estado, hashes, tiempos, provider y cobertura por corrida.
- research_documents: URL canónica/final, fetch, hashes, excerpt mínimo y locator verificable.
- research_signals: claim, entidad, dirección, confianza, TTL, conflicto y validación.
- research_conflicts: versiones incompatibles que requieren resolución explícita.
- cost_ledger: tokens reportados y subscription_usage=1; no inventa costo por token.

Un manifest se reutiliza si su contenido no cambió. Un plan idéntico no crea revisión. Una
solicitud de investigación referencia el hash exacto del manifest que recibió.
`memory_summary` se reconstruye determinísticamente en cada `prepare`: conserva hasta cuatro
revisiones de plan, ocho decisiones y ocho reviews de GWs estrictamente anteriores, y veinte
lecciones validadas no retiradas. Incluye comparación de revisiones, cobertura, estado de
promoción y hashes de evidencia; no copia evidencia extensa, chain-of-thought ni historial de
chat. Su propio SHA-256 permite demostrar exactamente qué memoria recibió Strategist.
`research_summary.focus` contiene primero los 15 elementos propios y después hasta diez candidatos del
batch baseline aprobado, resueltos contra el último snapshot público. Cada sujeto lleva notas
oficiales, p_play/p60 y razón de inclusión cuando están disponibles. La corrida siguiente recibe
las señales activas anteriores y debe producir deltas, no repetir claims sin cambios.
También recibe hasta ocho `reusable_evidence_hints` de la última corrida v2 importada del
mismo ciclo, con antigüedad máxima de 36 horas. Sólo se incluyen documentos con fetch
verificado que respaldaron sujetos todavía presentes en el foco. URL y
elementos cubiertos son pistas de descubrimiento, nunca evidencia transferida: el worker debe
volver a leer la página y el importador debe verificar de nuevo el fragmento y locator en el
brief actual. Una pista obsoleta o inaccesible no aumenta cobertura ni habilita señales.
La cobertura v2 incluye `teams` con sujetos requeridos, revisados y con evidencia verificada
por club. El total y el gate 90/80 siguen calculándose sobre los sujetos individuales; este
desglose diagnostica dónde se agota discovery y no concede cobertura adicional.

## Continuación autónoma de pendientes (1.17.0)

El timer conserva cada resultado parcial y puede encolar un hijo en el mismo slot.
`mova strategy research due` distingue `completion_pending`, `research_focus_complete`,
`research_focus_investigated_with_uncertainty`, `completion_budget_exhausted`, `completion_deadline_reserve`
y `completion_parent_artifact_invalid`. El hijo recibe IDs pendientes y fuentes
previas como pistas. Cada documento acreditado por la corrida pasa por el fetch
independiente. `coverage.campaign` muestra el progreso acumulado por jugador:
conserva la verificación en su corrida original, revalida sus hashes y vigencia,
y la invalida ante cambio de club/posición/noticias/status/chance oficiales,
fuente vencida/alterada o incertidumbre posterior. Las señales materiales además
conservan su TTL por tema. La acumulación no acredita una nueva verificación,
no altera el resultado por corrida ni la aceptación prospectiva; declara
`acceptance_eligible=false` y `permits_execution=false`. Un refresh de otra
ventana conserva los pendientes y sigue ejecutando su cadencia normal.
Desde T−72h el timer puede continuar cada 15 minutos sin validación humana,
sin tope adicional de tres runs por slot ni reserva especulativa para slots futuros.
El presupuesto compartido conserva sus techos reales por GW/mes/job y usos.
El corte de nuevas continuaciones sigue siendo T−80m (diez minutos antes de T−70m). Un fallo terminal no se reetiqueta ni genera un hijo.
La selección prospectiva sigue siendo el primer run y no se registra otra cohorte.
`campaign.investigation_status=complete_with_uncertainty` indica que todos tienen
fuentes verificadas pero quedan preguntas abiertas. No declara dudas resueltas:
`pending_evidence_subjects`, `open_questions`, `completed_subjects` y el estado
original siguen separados. El timer deja de gastar en esas mismas dudas dentro
del slot; el refresh siguiente las revisita. Sin fuente válida continúa parcial.
Fuentes/identidad/TTL y aceptación A3 no se rebajan.
Los antecedentes de un intento por slot descritos abajo corresponden al contrato
anterior; no implican que un parcial 1.13.0 haya completado el foco.

Para una continuación manual ya autorizada, usar `strategy research enqueue
--force --run-id research_PARENT --actor ... --reason ... --idempotency-key ...`.
Exige padre importado del ciclo vigente, hash íntegro y los mismos límites;
reutiliza un hijo ya existente en vez de duplicarlo. No abre ventanas de guardado
ni altera la aceptación prospectiva. El timer normal no necesita esta excepción.

### Cierre con límites de fuentes (1.17)

Investigar todo el foco no implica que exista una noticia reciente verificable
para cada jugador. `processed_subjects` separa trabajo terminado de evidencia:
`source_limited_subjects` exige dos URLs públicas distintas leídas por las tools,
en corridas importadas del slot vigente, con receipts físicos válidos y logs RPC.
Una nota del modelo, un receipt alterado o dos variantes query de una URL no bastan.
`complete_with_limits` conserva cobertura verificada, `not_checked`, dudas y límites
exactos; no afirma disponibilidad ni concede autoridad/aceptación. Un supported
que no llegó al brief sigue pendiente: no se oculta como ausencia de fuentes.
El próximo refresh reabre los límites. No se gasta indefinidamente repitiendo el
mismo dato que las fuentes no publican. Las búsquedas fallidas no son evidencia.

Los nombres cortos duplicados del catálogo, por ejemplo Palmer, se desambiguan
con el nombre completo del foco sellado. Exigen ese nombre completo en el fragmento,
tanto en la tool como en el importador; el apellido solo y el otro homónimo no pasan.
Una limitación antigua causada por ese bug sigue en retry hasta una lectura
atestada con 1.17+. Una corrida legacy posterior que busque pero omita verificar
no borra la ambigüedad anterior. Se conservan requests/resultados inmutables;
la corrección no convierte una lectura sin fecha válida en evidencia.

## Operación

El entrypoint host `deploy/bin/research-cycle.sh` carga `/etc/mova-fpl/deploy.env`
antes de interpolar Compose, tanto manualmente como desde systemd. Un `env_file`
del contenedor no selecciona la etiqueta de imagen del proceso Compose.


~~~bash
# consulta
mova strategy status
mova strategy research due
mova strategy research coverage
curl -s http://127.0.0.1:8787/api/v1/research/coverage | python -m json.tool

# activar una revisión explícita del plan
mova strategy plan --file /path/season-plan.json \
  --actor julian --reason "revisión del horizonte GW2–GW8"

# sellar el estado sin llamar al LLM
mova strategy prepare

# flujo manual equivalente al timer
mova strategy research enqueue
docker compose --profile research run --rm --no-deps -T research
mova strategy research import

# excepción auditada de cadencia
mova strategy research enqueue --force --actor julian \
  --reason "rueda de prensa material" \
  --idempotency-key "research:gw02:press-final"
~~~

due y un slot ya consumido devuelven código 75. El timer evalúa cada 15 minutos, pero Codex sólo
puede abrir una corrida en cada uno de tres slots: investigación amplia entre T-24h y T-6h,
refresco dirigido entre T-6h y T-2h, y corrida final entre T-120 y T-70 minutos. Baseline no
consume agente y después de T-70 no inicia research nuevo. Un fallo terminal consume el slot;
no se crean IDs nuevos para ocultarlo ni se eleva el presupuesto. Un tick sin request pendiente
no levanta el contenedor Codex. El
worker usa un lock exclusivo y procesa una solicitud; el importador procesa todos los resultados
listos. El límite del worker es ocho minutos y systemd conserva diez minutos para importación y
cleanup; timeout o salida 0 sin artefacto se registran como errores tipados y nunca como brief.

Antes de publicar el resultado, el worker aplica una reparación estructural determinista. Canoniza
URLs HTTPS, elimina documentos duplicados, descarta referencias que no apuntan a un documento del
mismo brief y reconstruye `coverage.subjects` exactamente en el orden del foco sellado. Una fila sin
evidencia se descarta o degrada a `not_checked`; nunca se agrega fuente, claim o señal. Además,
`generated_at` lo fija el reloj del worker al finalizar porque es metadata de ejecución confiable,
no contenido editorial del modelo. El reporte sanitizado queda en
`research/logs/<run_id>.normalization.json` con conteos, sin URLs ni texto de evidencia.

`mova strategy status` expone el ciclo vigente y también `service`: última corrida global,
conteos por estado, documentos, señales aceptadas y conflictos abiertos. Así la apertura de una
nueva GW no convierte falsamente el health histórico en cero. Prometheus publica además
`mova_research_runs_total`, `mova_research_last_import_timestamp_seconds`,
`mova_research_coverage_ratio`, `mova_research_evidence_ratio`,
`mova_research_measured_gameweeks`,
`mova_strategic_memory_status`, `mova_strategic_memory_items` y
`mova_strategic_plan_revision`. Un estado `empty` es válido al inicio de temporada; `invalid` o
`missing` exige volver a sellar el manifest antes de confiar en ese contexto.

## Aislamiento y auth

mova-research monta solamente:

- /var/lib/mova-fpl/artifacts/research como spool;
- /var/lib/mova-fpl/codex-home como CODEX_HOME persistente.

No monta repo, runtime.env, DB, modelos, perfil browser, password PostgreSQL ni key de odds.
Corre sin capabilities, con root filesystem read-only, usuario 10002 y herramientas Codex de
shell, Computer Use, browser, apps y multi-agent deshabilitadas. Solo quedan web search y la
salida estructurada.

Provisionar auth.json por un canal seguro, propietario 10002:10002, directorio 0700 y archivo
0600. Es una credencial: no imprimir, abrir en logs, copiar a Git, Supabase, artefactos de
evidencia o backups. El archivo debe persistir porque Codex puede refrescarlo. host-probe
publica únicamente auth_present=true/false.

## Criterios de aceptación

El importador rechaza y pone en cuarentena un brief si:

- supera 1 MiB o no cumple la identidad/hash del request;
- cita URL distinta de HTTPS pública, credenciales embebidas, IP privada o puerto no 443;
- usa una taxonomía desconocida, fecha futura, TTL vencido o elemento inválido;
- una señal o conflicto cita documentos ausentes.
- el request archivado ya no reproduce su hash, manifest o ciclo sellado;
- coverage omite, duplica o inventa sujetos fuera de `research_summary.focus`.

`published_at` admite timestamp ISO 8601 con zona o fecha civil `YYYY-MM-DD`; esta última se
normaliza a medianoche UTC sin inventar una hora editorial. `generated_at` y `expires_at`
siempre requieren zona horaria.

En briefs v2, search solo descubre URLs. El importador vuelve a obtener cada página con HTTPS,
valida cada salto contra SSRF, limita cuerpo a 2 MiB, permite únicamente texto/HTML/JSON y
localiza literalmente el `evidence_text` sobre texto normalizado. Conserva solo el excerpt de
máximo 800 caracteres, locator y hashes; no archiva la página completa. Los fetches usan ocho
workers como máximo y timeout individual de ocho segundos, con salida en orden determinista.

Una señal v2 se marca `accepted` solo cuando el locator quedó verificado y existe fuente oficial
verificada o al menos dos URLs verificadas, sin conflicto abierto. Una cita no recuperable,
fuente única no oficial o conflicto queda `candidate`. La confianza del modelo nunca reemplaza
este gate. Briefs v1 históricos permanecen legibles como `legacy_unmeasured/unverified`, pero no
cuentan para el gate de cobertura.

`mova strategy research coverage` conserva el reporte histórico por GW, incluidos fallos.
ADR-011 separa aceptación futura: `mova strategy acceptance contract` devuelve el contrato
actual; `mova strategy acceptance register --file MANIFEST --actor OWNER --reason MOTIVO
--idempotency-key CLAVE` registra un manifiesto `mova-research-acceptance-manifest-v1`
con `season`, `approval_reference`, el objeto `contract` exacto y `slots` explícitos
(`cycle_id`, `gw`, `opens_at`, `deadline_at` con timezone). Debe registrarse antes de
cualquier corrida de esas GWs. No admite GWs repetidas, retrospectivas ni solapadas con
otra cohorte. Cada nueva cohorte requiere su propia aprobación trazable.

`mova strategy acceptance status` y GET `/api/v1/research/acceptance` muestran todos
los slots y el historial separado. Readiness evalúa la última preregistración aprobada,
nunca la mejor cohorte. Se fija transaccionalmente la primera corrida operativa antes
que el worker obtenga autorización; experimentos/replay no cuentan. Incluso una corrida
fuera de la ventana permanece seleccionada y falla. Ningún resultado posterior la sustituye.
Todas las GWs deben superar individualmente 90 % cobertura, 80 % evidencia y cero conflictos
aplicables, con recibos completos, modelo/versiones/hashes iguales, consumo exacto dentro
del presupuesto y máximo dos intentos. Un intento fallido o incierto bloquea la aceptación.
Slots pendientes permanecen `in_progress`; al vencer sin resultado quedan fallidos.
No existe edición o eliminación de contratos/bindings en el writer SQLite.

El worker verifica sus hashes, Codex, modelo y effort antes de inferir. Los hashes del
worker/schema/prompt/contexto se publican en `research_acceptance_assets.json`; actualizar
ese inventario después de modificar sus fuentes y verificarlo con las pruebas. Cambios
materiales invalidan el contrato vigente. Señales históricas sólo sirven de contexto:
ninguna contradicción se declara resuelta y cada claim reutilizado requiere evidencia
independiente fresca sellada por el importador para el nuevo cutoff. Registrar o pasar
research no cambia presupuesto, compliance ni controles de ejecución FPL.

## Diagnóstico

### Adjudicar un falso conflicto temporal

`mova strategy research resolve-conflict --conflict-id ID --cycle-id CICLO
--document-id DOCUMENTO --actor OPERADOR --reason MOTIVO --idempotency-key CLAVE`
registra una revisión supervisada `not_contradictory`. Repetir `--document-id`
para cubrir **exactamente todas** las URLs originales del conflicto. Sólo admite
documentos del mismo run con fetch verificado, excerpt y artefacto cuyos hashes
siguen intactos. El operador debe explicar por qué los claims pueden coexistir;
por ejemplo, rendimiento en un partido anterior no contradice una duda médica
para el siguiente. La verificación de hashes no demuestra esa interpretación.

La transacción conserva el conflicto original en auditoría, registra actor,
motivo, fuentes y clave, y cambia únicamente su estado. Replay exacto reutiliza
el evento; una clave con contenido distinto o una segunda resolución falla.
No sirve para declarar una lesión resuelta, sustituir fuentes con otras nuevas,
aceptar riesgo sin evidencia ni resolver contradicciones reales pendientes.
No promueve señales, borra historia, altera modelos, controles o envelopes.
Después requiere una decisión nueva con los gates normales; no habilita FPL.
El CLI no se expone como endpoint HTTP ni se entrega al worker de research.

~~~bash
mova strategy status
mova doctor --json
systemctl status mova-fpl-research.timer mova-fpl-research.service
journalctl -u mova-fpl-research.service -n 100 --no-pager
find /var/lib/mova-fpl/artifacts/research -maxdepth 2 -type f -printf '%P\n'
~~~

- queued persistente: revisar service, auth y último error JSON; no mostrar contenido sensible.
- rejected: revisar el error sanitizado y quarantine; no insertarlo a mano.
- `resultado de research cruza el cutoff`: confirmar primero `generated_at` y después fechas de
  documentos. Un timestamp futuro del modelo se evita con el reloj del worker; una fuente realmente
  posterior al deadline sigue siendo rechazo correcto.
- un rechazo terminal mueve resultado y request a `quarantine`; el timer no vuelve a consumir
  Codex. Un replay requiere una nueva solicitud auditada, no copiar el request al inbox.
- coverage `insufficient_gameweeks`: condición esperada antes de tres ciclos v2; no rebajar el
  policy ni contar briefs legacy como evidencia.
- `evidence_*` fallido: revisar `fetch_status`, `fetch_error_code`, MIME/redirect y locator; una
  cita del proveedor no autoriza marcar el documento como verificado.
- auth ausente/expirado: detener el timer, renovar por canal autorizado, verificar permisos y
  reactivar.
- web/search no disponible: conservar el último brief aceptado hasta su TTL; no volverlo vigente
  artificialmente.

## Rollback

~~~bash
systemctl disable --now mova-fpl-research.timer
docker compose --profile research down
~~~

La migración es aditiva. El rollback de código conserva tablas, requests, resultados y audit.
No se borra la cola durante recuperación. Reponer la revisión anterior de checkout/imagen,
migrar solo hacia delante y ejecutar mova doctor. Nada de este flujo habilita browser writes.


## Researcher component release — 2026-09-22

The active registry selects **Researcher 1.10.0**, Astra/medium, Codex 0.153.4,
quality policy 2026.09.5 and brief v2. The [agent versioning decision](../decisions/agents/researcher-versioning.md)
and `experiments/research/20260922-agent-lab/` preserve definitions, measured
experiments, limitations and release evidence. Runtime deployment is `e903983`, with checkout/image parity and 24 passing doctor
checks after rollout. Inspect cockpit version, checkout/image SHA and doctor for
current state; Git selection alone is never proof of deployment. Rollback to
85365e8 is preserved under `/opt/orbital/backups/mova-fpl/researcher-e903983/`.

Two isolated live runs produced 12/25 and 10/25 verified focus subjects, six/seven
valid dated documents, four/five accepted signals, and one/two discoveries outside
focus. All final excerpts survived independent import. These are 48%/40% partial
coverage, not 90%/80% or three passing GWs. Exact-version repetition plus manual
claim/source review supports component release; it does not satisfy the stricter
same-manifest comparator or promote FPL authority.

The normal Compose worker now mounts the controlled search credential and exposes
only four evidence/context tools. Startup fails before inference on a missing or
unexpected tool surface. No database/browser credential or writable FPL tool is
available. Version/model/context hashes and real token receipts identify each run.
Broad/forced scope is 16 queries/documents; refresh/final retain delta scope.

Experimental requests remain isolated from operational evidence and cadence slots;
use the host research lock. The old 85365e8 importer must never process them.
The authorized campaign allowance preserves consumption and restores scoped token
and use capacity. The historical baseline overrun remains reviewed, not erased.
The scheduler still operates its predeadline slots; a component release does not
create a new daily background research schedule.


## Laboratorio de cobertura — candidato 1.11.0

La versión activa sigue siendo 1.10.0. El candidato 1.11.0 añade la hipótesis
`focus_completion_v1`: priorizar el foco pendiente mediante `research_context` sección
`focus_progress`, agrupar dudas por club y cerrar cada sujeto con evidencia o limitación.
El progreso cuenta verificaciones supported dentro del turno y permanece diagnóstico;
la importación independiente decide cobertura/aceptación. No completa silencios de búsqueda.
Modelo, calidad, scope, timeout y guard reactivo conservan los límites de 1.10.0.

Replay sin red ni inferencias:

```bash
python -m experiments.research.replay_corpus experiments/research/20260929-harness
python experiments/research/compare_agents.py /ruta/research baseline_run candidate_run
```

El comparador exige manifiesto, scope, calidad, contexto, método de fuente, implementación y
límite de tokens compatibles; ambos consumos conocidos y dentro de límite, una tentativa
completa por brazo, mejora de cobertura >=2 sujetos y ausencia de regresión de conflictos
/soporte. Los hashes de contexto se reportan; incluyen versión e identidad de request y no
se exige igualdad byte a byte. Falta de evaluación o metering nunca se inventa.
Una comparación elegible es candidata a revisión, no promoción ni aceptación multi-GW.

El corpus contiene seis extractos reales con hashes verificados y ocho etiquetas de contrato.
Conserva fechas de captura y limita su uso retrospectivo: una captura posterior al deadline
no entra al backtest de esa GW. Los checks léxicos no validan todo el significado de un claim.
Antes del ensayo online pareado de máximo 2M tokens, comprobar presupuesto y conservar
capacidad operativa. El snapshot de 29/09 03:11 UTC dejó 2.310.934 tokens en la GW: un par de
2M dejaría 310.934, menos que un job operativo de 1M. El par se difiere sin ampliar allowances.

## Iteración operativa 04/10/2026 UTC

La candidata Researcher **1.12.0** agrega `club_first_pass_v1`: deriva del foco
sellado una primera pasada por club, prioriza sujetos propios y exige intentar
clubes sin cobertura antes de repetir discovery de un club ya cubierto. Una alerta
material puede requerir corroboración; después vuelve a los grupos pendientes.
No aumenta consultas, documentos, tiempo ni tokens. Conserva fecha verificada,
conflictos históricos y `not_checked`; no interpreta una noticia de otro período
como evidencia contemporánea ni como alta médica. La activa permanece **1.10.0**.

La última cobertura viva observada es **12/25 = 48%**, con siete de quince sujetos
propios verificados y cinco de diez candidatos. Es evidencia parcial del 22/09,
no información fresca del 04/10. El foco se distribuye en trece clubes y varios
quedaron sin evidencia; el candidate intenta evitar repetir discovery sobre los
grupos ya cubiertos. Su efectividad necesita un experimento comparable, con uso
real registrado; no acredita una GW passing ni resuelve conflictos existentes.

Cuatro conflictos siguen sin resolver (uno en GW6). No se borraron ni se cerraron
con noticias actuales: `resolve-conflict` exige exactamente los documentos del
run original con hashes verificados. Un documento sin fecha fiable no autoriza
resolver una contradicción temporal. Research coverage 90/80 y tres jornadas
passing mantienen sus requisitos.

## Preparación pareada y auditoría — 04/10 UTC

El [protocolo preparado](../../experiments/research/20261004-preparation/README.md)
fija 1.10.0 / 1.12.0 con entrada común, contratos, método de fuentes, presupuesto
máximo y reserva operativa. El par queda deferred: 2.310.934 tokens GW frente a
3M requeridos para dos brazos y un job operativo. No se encoló ni amplió allowance.
Se comparan agenda y distribución conjuntamente; aislar distribución requiere
1.11.0 / 1.12.0. Resultados, metering y capacidad se revisan de nuevo al ejecutarlo.

`audit_conflicts.py` verificó los originales sellados sin descargar web de nuevo.
Los dos conflictos de Haaland conservan artefactos/fragmentos íntegros pero sin
publicación verificada; los otros dos son legacy_unverified sin evidencia original
sellada. Los cuatro permanecen abiertos. Una resolución exige evidencia original
suficiente y revisión semántica; el auditor sólo clasifica, no adjudica.
