---
type: proposal
name: "MOVA FPL — descubrimiento global del Researcher"
created: 2026-09-20
updated: 2026-09-20
tags: [mova, fpl, research, evaluation, harness]
status: implementation-in-progress
---

# Researcher: descubrir cambios antes de seleccionar jugadores

## Estado y pregunta

Esta es la propuesta y bitácora de implementación de AC-02, no una nueva hoja de ruta.
La autoridad operativa, el gate 90/80 y las tres GWs independientes permanecen en
[04-readiness-and-rollout.md](04-readiness-and-rollout.md). El runtime vigente se describe
en [strategic-research.md](../../operations/strategic-research.md): plantilla de 15,
hasta diez candidatos del modelo, investigación web sellada, SQLite writer y shadow A0.
Ninguna señal de research altera por sí misma el equipo o la cuenta FPL.

Pregunta de diseño: ¿cómo dejar al agente descubrir hechos relevantes en toda la liga sin
convertir cada jugador en un job LLM, fabricar cobertura ni gastar más que el valor de la
información encontrada?

## Corrida retrospectiva manual, 20/09/2026

Se compararon el foco y los resultados de Researcher importados, los batches baseline
aprobados en PostgreSQL y fuentes web públicas. Los cortes de GW3, GW4 y GW5 fueron
04/09 17:30, 12/09 12:30 y 18/09 17:30 UTC. GW3 y GW4 están `data_checked=true`;
GW5 sigue sin settlement verificado. Las páginas abiertas hoy tienen fecha editorial,
pero no una captura inmutable anterior al deadline: sirven para formular hipótesis,
no para certificar un backtest sin fuga temporal.

| Caso | Señal pública y momento editorial | Qué recibió/hizo MOVA | Lectura prudente |
| --- | --- | --- | --- |
| Rodon, GW3 | [Leeds, 03/09](https://www.leedsunited.com/en/news/daniel-farke-provides-fitness-update-ahead-of-brighton-clash-a): lesión de isquiotibiales y estimación de 8–10 semanas. | Propio en foco con bandera FPL de 75%; research marcó empeoramiento con artículos del 30/08, sin la duración del parte nuevo. Baseline predeadline ya lo tenía en `p_play=0`, `xP=0`. | Fallo de frescura y horizonte plurijornada; **no** prueba mejora de la decisión inmediata. |
| Gibbs-White, GW3 | [PL Scout, 03/09](https://www.premierleague.com/en/news/4706086): había ejecutado un penalti y recuperado parte de las jugadas a balón parado. | Candidato en foco; research destacó riesgo físico con noticia más antigua. Baseline ya lo ordenó tercero por xP. | Una investigación centrada en disponibilidad omite cambios de rol. El rol es hipótesis incremental, no garantía de puntos. |
| Lewis Hall, GW3 | [PL Scout, 03/09](https://www.premierleague.com/en/news/4706086): seis córners/faltas laterales y calendario favorable. | Fuera de los 25 del foco; baseline lo ordenó 38.º. | Ejemplo de candidato de descubrimiento global con horizonte de varias GWs; no demostraría por sí solo que debía entrar al equipo. |
| Szoboszlai, GW4 | [PL Scout, 11/09](https://www.premierleague.com/en/news/4713402/scout-selection-best-fantasy-team-for-gameweek-4): ejecutaba córners/faltas y había cobrado un penalti. | Candidato en foco; research devolvió `no_material_update` con una alineación europea del 09/09. Baseline ya lo ordenó segundo. | La cobertura nominal no equivale a investigar el rol relevante. Su GW4 de tres puntos no invalida la señal de rol. |
| De Cuyper, GW4 | [PL Scout, 11/09](https://www.premierleague.com/en/news/4713402/scout-selection-best-fantasy-team-for-gameweek-4): defensa usado como mediocampista izquierdo. | Fuera del foco; baseline rango 76, `xP≈3.34`. Marcó 11 puntos en GW4. | Oportunidad de descubrimiento para contrastar posición/minutos con el modelo; los 11 puntos no prueban causalidad ni que el traspaso fuese óptimo. |
| João Pedro, GW5 | [PL alineaciones previstas](https://www.premierleague.com/en/news/4720146): duda física reciente. La hora de publicación/actualización respecto al deadline no está preservada. | Propio en foco; research `unresolved` usó un reporte del 13/09 sobre apariciones previas como contrapeso. Baseline `p_play≈0.714`. | Un partido anterior no refuta una lesión posterior. Requiere orden temporal y fuente fechada; caso provisional hasta certificar disponibilidad de la página y settlement GW5. |

La observación más sólida no es «habríamos ganado X puntos». Es que el foco cerrado
excluye hechos de rol potencialmente útiles y que `verified_excerpt`/coverage pueden
coexistir con evidencia vieja o semánticamente insuficiente. Hace falta medir la
**novedad frente al modelo y frente a señales previas**, no contar URLs o sujetos
nombrados como calidad de investigación.

## Contrato propuesto del harness

1. **Contexto sellado.** Construir un `ResearchWorldSnapshot` por deadline: season
   plan (objetivo, horizonte, guardrails), team state, fixtures, universo oficial de
   elementos/clubes, modelo baseline y su linaje de inputs, flags FPL, research activo,
   reviews y lecciones validadas. El agente recibe un resumen compacto con acceso de
   lectura a detalles por ID; los nulos de proyección no se interpretan como cero.
2. **Radar global determinista.** Comparar snapshots as-of de todos los clubes y
   jugadores, sin una llamada LLM por elemento. Disparadores: lesión/retorno y
   duración, cambio de titularidad/minutos, posición o rol, penaltis/balón parado,
   fichajes y competencia por puesto, suspensión, fixture/odds y cambios que afecten
   indirectamente a compañeros o rivales. Deduplicar hechos ya codificados en
   modelo/FPL. El radar produce temas y entidades, no recomendaciones.
3. **Descubrimiento autónomo acotado.** El Researcher puede proponer búsquedas por
   club, tema o anomalía fuera de los 25 del foco y justificar por qué importan para
   el horizonte del plan. Un adaptador de búsqueda mide y **hace cumplir** consultas,
   URLs, tiempo y presupuesto; un límite escrito en el prompt no es límite duro de
   búsqueda nativa. Reservar cuota separada para radar global, seguimiento de
   sujetos propios y verificación cerca del deadline; parar y reportar `not_checked`
   al agotarla.
4. **Evidencia por claim.** `DiscoveryLead` contiene `fpl_element_id`, club, tema,
   claim, evento y fecha de publicación, URL, motivo de relevancia, novedad estimada,
   TTL y coste. Adquisición segura guarda captura/hash/fecha/locator. Un verificador
   exige que el fragmento respalde **ese sujeto y ese claim**, no solo que aparezca
   literalmente en la página. Diferenciar publicación de evento y de última edición;
   ante una página mutable sin copia as-of, degradar la certeza retrospectiva.
   Mantener `unresolved` si dos fuentes vigentes chocan; la ausencia de novedad
   respaldada no se convierte en `no_material_update` por haber abierto una URL.
5. **Relevancia y novedad.** Clasificar `already_in_model`, `already_in_research`,
   `candidate_incremental`, `conflicting` o `unresolved` mediante comparación con
   los inputs y la predicción del batch exacto. Estimar impacto potencial en
   disponibilidad, xP, transferencias/capitán, competidores y próximas GWs; esta
   estimación prioriza verificaciones, **no** modifica el modelo ni ejecuta FPL.
   Una watchlist entre GWs retiene leads con TTL, último chequeo y disparador de
   reapertura, en vez de repetir narrativas en cada ventana.
6. **Salida separada.** Publicar `DiscoveryLead`, `VerifiedSignal` y `ResearchBrief`
   distintos. El brief comunica al Strategist lo nuevo, lo ya sabido, conflictos,
   cobertura realmente comprobada y temas no revisados. Mantener provenance,
   attempt/cost receipts y hashes por etapa para replay. La máquina determinista
   y los gates existentes siguen siendo la única autoridad de decisión/ejecución.

Esto concreta la separación discovery→acquisition→extraction→policy de
[ADR-010](decisions/ADR-010-evidence-first-research.md), que sigue `proposed`.
La política de fuente debe favorecer club/PL y datos oficiales para hechos; columnas
de Scout y alineaciones previstas plantean hipótesis de rol o XI y requieren
corroboración antes de elevar confianza.

## Evaluación y secuencia de implementación

**Primera iteración: replay hermético antes de cambiar producción.** Congelar para GW3
y GW4 los manifiestos, batches e inputs originales; conseguir capturas con timestamp
anterior a cada deadline o marcar cada artículo no certificado. Etiquetar los casos
anteriores y algunos controles negativos (noticia vieja, sujeto homónimo, lesión ya
incluida en `p_play`, página inaccesible). Ejecutar baseline y prototipo con el mismo
cutoff, fuentes, cuota y presupuesto. GW5 queda como prueba provisional, fuera de
las métricas de resultado hasta `data_checked=true`.

Medir por separado: recall de leads materialmente relevantes **dentro y fuera del
foco**, precisión de claim/identidad/tiempo, novedad verdaderamente incremental,
resolución de conflictos, coste en tokens y consultas por lead validado, latencia y
degradación cuando no hay evidencia. Una segunda comparación pareada pregunta si
la señal cambia una predicción o decisión factible; los puntos reales solo se
evalúan post-settlement y con contrafactual de decisión, nunca como etiqueta única
de calidad. Registrar los leads hallados por el prototipo que el baseline omitió y
los falsos positivos que introdujo.

Después, implementar el radar y el adaptador de búsqueda bajo feature flag shadow;
añadir verificación semántica/temporal por claim y tests de fixtures para los casos
etiquetados. Solo entonces cambiar el contrato de request/brief y el gate de calidad
por versión. **No rebajar ni sustituir silenciosamente** el 90/80 vigente: publicar
junto a él cobertura del radar global, precisión de señales y coste; proponer un
gate nuevo en AC-02 con Nicolás antes de cualquier promoción. Exigir tres GWs
independientes settled, costo dentro de presupuesto y deliberación terminal sobre
envelope vigente. Hasta ese punto, todo corre A0 shadow sin escrituras FPL.

## Auditoría del harness y de la base, 20/09/2026

Código vigente: `StrategicContextService.prepare()` sella manifest y memoria;
`AnalyticsStore.research_focus()` entrega 15 propios y hasta diez candidatos por xP;
`codex-worker.mjs` pide coverage-first y prohíbe barrido de liga;
`SafeEvidenceFetcher` verifica solo presencia literal del excerpt;
`_validate_signals()` acepta una fuente oficial verificada o dos URLs verificadas;
`_validate_coverage()` cuenta como comprobado un sujeto asociado a una URL verificada.
Ninguna de esas dos últimas funciones comprueba que el texto pruebe **el claim
individual**, su vigencia frente al evento más reciente o novedad frente al batch.
Además, el prompt llama «hard limits» a `max_web_queries`, pero `codex exec --search`
no ofrece al host un contador/control obligatorio de cada consulta interna. Los
máximos de documentos y señales sí pueden validarse en la salida.

La inspección read-only del VPS mostró 9 filas en `research.runs`, 50 en
`research.documents`, 58 en `research.signals` y 7 en `research.conflicts` en
PostgreSQL shadow. El writer de esos registros continúa en SQLite `ops.db`; los
nombres PostgreSQL son una proyección de importación, no un segundo writer.
Hay cuatro runs v2 importados: GW3 18/25 comprobados y 15/25 con evidencia;
GW4 broad 11/25 y 9/25, refresh 6/25 y 6/25; GW5 6/25 y 6/25. La última
cobertura por GW falla 0/3 medidas. Esas cuatro ejecuciones suman 816 127 tokens
reportados en el cost ledger (input + output), sin precio monetario atribuible
a la suscripción. En señales v2 aceptadas/candidatas se observaron
`availability`, `starting_role`, `fixture_context`, `injury` y `other`, **cero
`set_pieces`**. «Accepted» hoy significa evidencia técnica/tier, no utilidad ni
corrección semántica.

El manifest de GW5 tiene 25 sujetos, campos FPL oficiales y `xp/p_play/p_60`
cuando entran en la consulta top-N. Algunos propios quedan con proyección `null`
por ese límite aunque exista proyección completa en PostgreSQL. `memory_summary`
sí recupera decisiones/reviews de GWs previas y solo lecciones validadas, pero
el Researcher ve del plan principalmente ID/revisión/rationale/horizonte; no recibe
supuestos, ventanas de chips ni guardrails completos. `previous_active_signals`
y `reusable_evidence_hints` miran **solo el mismo ciclo**; falta continuidad
semántica entre GWs. Esta combinación explica por qué el agente conoce una lista
de personas, pero no siempre el objetivo y el contexto que hacen valiosa una
noticia para varios partidos.

### Responsabilidad de cada componente después del refactor

| Componente | Responsabilidad única |
| --- | --- |
| Preparador determinista | Sella cutoff, batch, plan activo, equipo, fixtures, universo FPL, deltas estructurados y priorización inicial. Rechaza IDs dudosos y datos futuros. |
| Un Researcher | Elige temas/consultas dentro de cuotas, encuentra leads también fuera del foco, extrae hipótesis y explica posible impacto. No declara verdad ni modifica entradas del modelo. |
| Fetch + adjudicador | Recupera fuente pública, sella locator, valida identidad, tiempo, claim, corroboración, conflicto y novedad contra inputs del batch. |
| Brief y evaluador | Da al Strategist señales aceptadas y límites; calcula métricas reproducibles y seguimiento entre GWs. |

No hace falta añadir un swarm de especialistas, un vector store nuevo ni un scraper
de prensa por tick. El mismo job puede hacer discovery y follow-up, pero debe tener
un contrato de salida que distinga ambas fases. El coste mayor debe concentrarse
en las excepciones que una búsqueda estructurada no resuelve.

### Contexto exacto para el Researcher

Entregar un `research_context_v3` sellado dentro del request, derivado sin texto
libre no validado:

- `as_of_at`, `deadline_at`, GW/horizonte (por ejemplo próximas 3–5 GWs), fase,
  IDs y hashes de manifest, batch y snapshots; `data_quality` de cada fuente.
- Objetivo de temporada resumido desde el **plan activo completo**: horizonte,
  supuestos, ventanas de chips y guardrails; sin convertirlo en permiso de ejecución.
- Equipo propio completo con capitán, banca, FT, banco, flags FPL y proyecciones
  para los **15** resueltas por ID exacto del batch (nunca `null` por top-N).
- Lista compacta de candidatos por xP y, por separado, la tabla de elementos,
  equipos, posición, precio, fixture y baseline necesario para identificar
  cualquier lead fuera del foco. No enviar proyecciones extensas en el prompt:
  un artefacto de lectura sellado permite lookup acotado por ID.
- Señales activas y watchlist **de GWs previas**, con fingerprint, TTL,
  `last_checked_at`, si el modelo ya absorbió el hecho, y disparador de reapertura;
  reviews/decisiones anteriores resumidas, únicamente lecciones validadas.
- Preguntas pendientes generadas por deltas: oficial FPL vs p_play, baja de un
  competidor, nuevo ejecutor de balón parado, minutos/posición, calendario.

El contexto estratégico tiene que decir *qué optimizamos y por cuánto tiempo*;
el catálogo global dice *a quién puede descubrir*; el batch exacto dice *qué
sabíamos ya*. Cada uno lleva fecha y hash. Si falta batch, equipo o plan, el
request declara `degraded` y reduce el alcance en vez de rellenar nulos.

### Selección de investigación y señales

El radar calcula deltas baratos entre snapshots, no busca a todos los jugadores
en web. Prioridad propuesta (configurable y auditada):

1. Disponibilidad nueva del equipo propio, capitán y candidato de transferencia;
   duración de lesión, suspensión, retorno y posible reemplazo.
2. Cambios globales de rol con efecto plausible: titularidad/minutos, posición
   real distinta de la clasificación FPL, penaltis, córners, faltas, competencia
   por fichaje/salida, cambios de entrenador o fixture.
3. Anomalías del modelo: xP alto con riesgo de minutos; oportunidad fuera del
   top diez por rol/fixture; cambios del rival que afectan clean sheet/ataque.

El agente puede abrir un tema nuevo y justificarlo; el preparador no le dicta
los 25 nombres como universo cerrado. Debe emitir `lead` aun cuando no haya
evidencia suficiente, con `unresolved`/`not_checked` honesto. Las señales de
Scout o alineaciones previstas son hipótesis; club/FPL/PL oficial con fecha
relevante tienen más peso, pero una fuente oficial sobre un partido pasado no
resuelve un evento futuro. El adjudicador separa cuatro preguntas: ¿la página
existe?, ¿identifica al sujeto?, ¿respalda el claim?, ¿era vigente al cutoff?
Después pregunta si el batch o el research anterior ya lo sabían.

### Persistencia mínima

Conservar las cuatro tablas actuales y sus IDs. Proponer **una** tabla nueva
`research_leads` en SQLite, replicada como `research.leads`, para que el radar
global y la watchlist sobrevivan a cada GW. Campos esenciales: `lead_id`,
`season`, `first_gw`, `last_gw`, `player_element`/`club_id`, `topic`,
`claim_fingerprint`, `status` (`new`, `watching`, `verified`, `dismissed`,
`expired`), `first_seen_at`, `last_checked_at`, `expires_at`,
`source_document_id` nullable, `signal_id` nullable, `novelty_status`,
`reason_code`, `model_batch_id` y hashes del snapshot/contexto. Índice único
por temporada+sujeto+tema+fingerprint para dedupe; eventos de cambio en el
ledger de auditoría existente, no otra tabla de historia.

Agregar a `research.signals`/SQLite solo columnas consultables indispensables:
`effective_at`, `claim_status`, `novelty_status`, `lead_id` y
`model_batch_id`. El detalle explicativo (tipo de efecto, corroboración,
locators por claim, regla de TTL y versión de policy) cabe en el JSON de
evidencia existente. `research.runs` conserva request/result/usage/coverage;
un `quality_report` versionado puede vivir en `coverage_json` y en artefacto
sellado. `research.documents` ya tiene URL, publisher, tiempos, hashes y
excerpt. **Problema pendiente:** hoy guarda hash y excerpt mínimo, no los
bytes completos de la página; por tanto no permite reproducir el contenido
as-of de una página mutable. Para replay, almacenar una captura normalizada
inmutable solo de las fuentes efectivamente usadas, bajo límites/licencias,
con hash y retención definidos; si no se puede, marcar `as_of_unproven` y
excluir el caso de la etiqueta gold.

No escribir research en Supabase: ahí solo vive PM. Las migraciones deben
mantener SQLite writer, importación con paridad a PostgreSQL shadow y lectura
de briefs v1/v2 históricos; v3 no reinterpreta registros viejos como passing.

### Scorecard que mide trabajo útil

Cada corrida publica denominador, numerador, corte temporal, versión de policy
y `unknown` cuando no hay verdad de referencia:

| Métrica | Definición y uso |
| --- | --- |
| Integridad de contexto | 15/15 propios con ID/batch/proyección o causa tipada; manifest y plan activos; fuentes frescas. Bloquea inferencias si falla. |
| Descubrimiento global | Leads verificables fuera del foco / leads relevantes fuera del foco de un gold set anotado; reportar también por tema y club. |
| Precisión de claims | Claims correctos en sujeto, contenido, tiempo y cutoff / claims adjudicados; falsos positivos de lesión o XI cuentan severamente. |
| Novedad incremental | Señales aceptadas **no** presentes en inputs del batch ni research activo / señales aceptadas. Separar `known_to_model` de `new`. |
| Cobertura dirigida | Riesgos prioritarios revisados con fuente pertinente / riesgos prioritarios elegibles; conservar 90/80 legacy por separado. URL genérica no da crédito. |
| Resolución y continuidad | Conflictos resueltos con evidencia nueva, leads reabiertos/cerrados por GW, TTL expirados a tiempo, claims duplicados evitados. |
| Utilidad para decisión | Señales que cambian una predicción/intervención factible en replay pareado; observar también señales válidas que no cambian decisión. Nunca inferir causalidad solo por puntos. |
| Economía y fiabilidad | Tokens input/output, búsquedas y fetches **contados por adaptador**, segundos, coste por lead incremental verificado, overruns, fallos y recuperación. |

El panel distingue `coverage`, `evidence_validity`, `incrementality` y
`decision_value`; no reduce calidad a una media. Alertar por cualquier hecho
post-cutoff aceptado, identidad equivocada, claim sin respaldo, saldo excedido
o degradación sostenida, aun si la cobertura nominal sube. Puntos reales
solo después de `finished && data_checked`, comparando la misma decisión
factible con y sin señal bajo el mismo cutoff.

### Plan de trabajo y gates

1. **Dataset y contratos.** Sellar GW3/GW4 como casos as-of donde haya captura
   válida, GW5 provisional; añadir controles negativos de artículo viejo,
   titularidad ya codificada, homónimo, conflicto temporal y página editada.
   Etiquetado independiente del output del nuevo Researcher. Congelar rúbrica.
2. **Corrección de integridad.** Resolver las proyecciones de los 15 propios,
   incluir plan completo resumido y linaje del batch, y cerrar la validación
   semántica/temporal por claim con fixtures. Esto aporta valor aunque no haya
   radar global. No cambiar la interpretación de runs anteriores.
3. **Radar + lead.** Una migración de leads/watchlist, delta determinista de
   catálogo/FPL/fixtures y una ruta global acotada para el mismo worker. El
   adaptador de búsqueda debe imponer cuota en código; mientras Codex native
   search no permita hacerlo, su límite es presupuesto/timeout por job y
   las consultas se reportan como `unobserved`, nunca como conformes.
4. **Replay pareado.** Mismo cutoff, fuentes elegibles, batch y presupuesto
   para v2 vs v3. Medir recall/precisión por clase, falsos positivos, utilidad
   y tokens por lead. Cero evidencia posterior al cutoff e identidad errónea.
5. **Shadow longitudinal.** Activar v3 por feature flag en A0, conservar brief
   v2 y gate 90/80 visible. Tras tres GWs settled independientes, fijar un
   gate v3 con umbrales pre-registrados y revisión técnica de Nicolás. Solo un
   proceso distinto podría promover autoridad FPL; research nunca la obtiene.

La primera entrega implementable es **integridad del contexto + validador de
claim + replay etiquetado**. No requiere nueva tabla ni proveedor. El radar
global y su tabla vienen después de comprobar que una señal nueva se puede
identificar y verificar correctamente. Así evitamos escalar una tubería que
todavía confunde presencia de texto con evidencia útil.

### Implementación del 20/09/2026 en este checkout

La primera entrega se implementó sin migración: proyecciones de los 15 propios por ID,
plan completo resumido, catálogo y fixtures oficiales acotados por cutoff, alertas
estructuradas y pistas de señales de GWs anteriores. El mismo worker admite hasta dos
consultas sugeridas de descubrimiento global. El importador conserva como candidata
una señal con ID desconocido, excerpt sin identidad/tema, fecha ausente o fetch
posterior al deadline. Coverage no acredita una página genérica. `coverage.quality`
y Prometheus exponen los contadores. La continuidad usa señales previas existentes;
una tabla de leads permanece diferida hasta demostrar que los leads sin señal
requieren persistencia propia.

Esto **no** instala búsqueda con cuota interna verificable, comprensión semántica
completa, replay etiquetado suficiente ni tres GWs passing. La decisión de promoción
de autoridad sigue separada. El estado de deploy/pruebas se registra en la nota de
release correspondiente; este documento no lo presupone.

## Límites de esta revisión

La corrida retrospectiva es una muestra dirigida, no una estimación estadística
de recall ni un backtest causal. Los artículos públicos pueden haber sido
editados después del deadline; MOVA no almacenó entonces sus capturas. GW5 aún
no está verificado. Las posiciones y xP citadas provienen del batch baseline
aprobado, no de un rerun con conocimiento futuro. Las métricas de base provienen
de una lectura del VPS a 20/09/2026 y cambian con nuevos imports. El siguiente
paso empírico es un dataset as-of versionado.
