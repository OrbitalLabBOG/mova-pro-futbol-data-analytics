---
type: project
name: "MOVA FPL Autonomous Operator 2026/27 — Readiness and Rollout"
created: 2026-08-21
updated: 2026-09-20
tags: [mova, fpl, readiness, rollout]
status: active-shadow
---

# Readiness y rollout

## Cierre de autonomía operativa — 20 de septiembre de 2026

Esta es la única hoja de ruta de cierre vigente. Sustituye la planificación C1–C5 del
14 de septiembre y los workpacks iniciales aún abiertos, no sus contratos ni su evidencia.
`10-autonomous-harness-v1.md` conserva la arquitectura. Supabase conserva tareas, responsables,
colas y compromisos; esta spec define resultados y aceptación, no un inventario PM vivo.
Esta revisión de hoja de ruta conserva la separación entre desarrollo, despliegue y
autoridad: ninguna tarea PM o commit activa A2/A3 ni nuevas escrituras FPL.

### Objetivo y límites

Cerrar el recorrido captura → investigación → decisión/validación → ejecución única →
verificación → settlement oficial → review → siguiente ciclo, sin intervención rutinaria.
Excepciones que requieren al humano, como reautenticación exigida por FPL, se detectan temprano,
se notifican y mantienen el último estado verificado. No se promete login perpetuo.

No incluye un motor nuevo, ampliar roles LLM, auto-modificación sin revisión ni migrar el
writer operativo como prerrequisito. Modelado y cutover PostgreSQL conservan sus líneas propias.
Una mejora estadística no concede autoridad; aprobar el backlog tampoco habilita el executor.

### Baseline observado y evidencia

Corte vivo: 2026-09-20 20:49:19–20 UTC, GET loopback `/api/v1/readiness` y
`/api/v1/harness-scorecard`. Readiness 17 pass, 9 pending, 1 blocked sobre 27; A0 elegible.
Runtime healthy; shadow/A0, kill switch on, writes off, compliance pending.

| Área | Hecho observado | Consecuencia |
| --- | --- | --- |
| Runtime | Operaciones 7/7; recuperación host 5/5 histórica; recuperación del 20/09 documentada | Consolidar release y comprobar estabilidad posterior; salud instantánea no equivale a autonomía |
| Datos | GW6 preliminary mientras GW5 no tenga finished+data_checked; baseline GW6 aprobado | Esperar cierre; no producir evaluación causal retrospectiva |
| Research | 3 GWs medidas, 0 passing; último brief 24% cobertura/evidencia, 142427 tokens | Bloqueo real de calidad; no sólo espera longitudinal |
| R2 | Capitanía 0/3, lineup 0/3; entrypoint sólo capitanía | Completar integración y evidencia por capacidad/versión |
| R3 | 1/3; entrypoint off y no promovido | Contrato/probe no prueba confirmación real |
| Continuidad | Closeout instalado, 0 completos vivos; feedback 3 propuestas, 0 evaluaciones y 0 lecciones | Ejercer el circuito completo sin exigir una mejora positiva |
| Alertas | local_only; destino y live ping ausentes | Falta operación desatendida fuera del proceso |
| Durabilidad | Paridad/roles pass, 4 ciclos PG; off-host sin configurar/restaurar | Conservar separación de writers y completar recuperación externa |
| Costos | Overrun histórico 355066/160000 reviewed_pending; cero reservas huérfanas | Exigir follow-up equivalente; una corrida menor distinta no cierra ese caso |

Evidencia de recuperación: [acta del 20/09](../../decisions/2026-27/runtime-recovery-20260920.md).
La escritura humana de GW5 no suma rehearsals del driver. Los contadores anteriores son
snapshots fechados; se vuelven a consultar antes de promover.

### Corte de infraestructura — 20 de septiembre, 20:38 COT

Readiness vivo: 21 pass, 5 pending, 1 blocked sobre 27; A0/shadow, kill switch activo y
browser writes deshabilitados. Cuatro gates de integración pasaron desde el baseline:
destino externo de alertas, live ping, backup cifrado off-host y restore aislado. El canal
es DM del bot Orbital a Julián; prueba auditada `job_78c9dd7e94fb4a5fb99c3d93cd82e359`,
aceptada por Slack y ligada al fingerprint sanitizado del destino. El bucket dedicado GCS
`orbital-lab-483815-mova-fpl-backup-20260920` usa una cuenta de servicio acotada,
credenciales root-only y contraseña de recuperación en Secret Manager. La copia terminó con
servicio `success`, timer `enabled/active`, seis archivos sellados y sin sidecars WAL/SHM.

El restore remoto final `job_a18aa088ecab4e1eb96250e69ebcb6f6` sobre la revisión
`1312d13` pasó 8/8 checks en 531 s de ensayo, con `downtime_seconds=0`, sin reiniciar
servicios ni mutar FPL; la base PostgreSQL temporal y el árbol descargado se eliminaron.
La [guía de VPS](../../operations/vps.md) documenta el procedimiento ante pérdida total.
Esta evidencia cierra AC-06/07 de infraestructura, no AC-03 ni AC-08: research sigue
bloqueado por calidad y faltan jornadas/ejecuciones longitudinales y closeout vivo.

### Entregables y aceptación

Los IDs AC siguientes identifican la evidencia exigida. Una tarea sólo termina cuando cada
criterio aplicable tiene un resultado y una referencia verificable; `not_exercised` no es pass.

| Clave de entrega | Tarea canónica / reutilización | Resultado y aceptación |
| --- | --- | --- |
| AC-01 Release y sesión | Nueva `FPL-CLOSEOUT-RELEASE` | Release reproducible: SHA/digest, hotfixes y overrides inventariados, rollback comprobable. AC-01.1: mismos artefactos/configuración explican host e imagen. AC-01.2: ventana de observación y límites de CPU/RAM/retries definidos antes de medir, sin workers huérfanos ni rescates. AC-01.3: auth expirada se detecta, cooldown y aviso temprano; reinicio conserva perfil cuando el proveedor lo permite. |
| AC-02 Research útil | Reutilizar `FPL-AUTO-RESEARCH-PIPELINE` | AC-02.1: priorizar plantilla/candidatos, fetch/locator/TTL e identidad exactos; cobertura según política vigente. AC-02.2: noticias antiguas, contradicciones y fuentes inaccesibles tienen resolución trazable; ninguna evidencia se fabrica. AC-02.3: tres GWs passing y Strategist/Critic terminal sobre envelope vigente. AC-02.4: presupuestos y follow-up equivalente del overrun verificados. |
| AC-03 Continuidad del ciclo | Nueva `FPL-CLOSEOUT-LIFECYCLE` | AC-03.1: cada stage tiene entrada, salida terminal, hora objetivo, margen de recuperación y hard stop versionados. AC-03.2: reinicios, busy lock, datos stale, presupuesto agotado, research insuficiente y auth caída terminan en recuperación acotada o escalamiento; sin retry ciego ni decisión antigua ejecutable. AC-03.3: ejecución verificada conduce automáticamente a settlement/review/siguiente ciclo cuando FPL cierra, conservando cutoff e idempotencia. AC-03.4: retorno no-action o sin hipótesis suficiente es válido y auditable. |
| AC-04 Ejecución R2 | Reutilizar `FPL-HV1-07D` | AC-04.1: entrypoints capitanía y XI/banca implementados y verificados. AC-04.2: pre-state, ejecución única, reload/post-state coinciden. AC-04.3: tres GWs distintas por capacidad/versión según ledger. AC-04.4: deriva DOM, crash y save ambiguo reconcilian sin duplicar; habilitación requiere autoridad separada. |
| AC-05 Ejecución R3 | Reutilizar `FPL-HV1-07E` | AC-05.1: adapter productivo cubre transferencias, hits y chips con FT/banco/precios exactos. AC-05.2: preview coincide y existe una sola confirmación irreversible; pérdida de respuesta exige lectura/reconciliación antes de reintentar. AC-05.3: tres GWs válidas por contrato y evidencia específica de capacidades no ejercidas. AC-05.4: límites deportivos versionados, ventana y autorización A3 verificadas. |
| AC-06 Alertas externas | Reutilizar `FPL-AUTO-ALERTING` | AC-06.1: destino y owner reales. AC-06.2: configured/live_proven corresponden al mismo fingerprint. AC-06.3: recepción, dedup, retry, acuse y ruta de fallo comprobados; HTTP 2xx no equivale a lectura humana. Enviar prueba requiere autorización del canal. |
| AC-07 Recuperación externa | Reutilizar `FPL-AUTO-OFFSITE-BACKUP` | AC-07.1: destino/owner, copia cifrada, retención y timer. AC-07.2: restore aislado con ocho checks e integridad. AC-07.3: excluir perfil browser/CODEX_HOME y secretos; documentar recuperación de pérdida del VPS y vigencia de la prueba. |
| AC-08 Aceptación longitudinal | Reutilizar `FPL-AUTO-SHADOW-DRILLS` | AC-08.1: matriz GW/capacidad/versión/SHA, sin inflar contadores por reintentos. AC-08.2: ensayos de excepciones y cero duplicados/huérfanos sin tratamiento. AC-08.3: una GW completa posterior a promoción, hasta review/siguiente ciclo, sin comandos de rescate. AC-08.4: expediente final distingue capacidad probada, no ejercida y restricciones. Es dueña de la evidencia viva; AC-03 es dueña de la integración. |
| AC-09 Expediente de promoción | Nueva `FPL-CLOSEOUT-PROMOTION` | AC-09.1: distinguir elegibilidad técnica, entrega integral y autoridad; resolver la relación de off-host/closeout con required_for sin modificarla por documentación. AC-09.2: decisiones de compliance y aprobación por capacidad registradas; límites, rollback y excepciones explícitos. AC-09.3: expediente A2 y luego A3, sin activar controles por cambio de estado PM. La aceptación final permanece en AC-08. |

El epic `FPL-HARNESS-V1` se reutiliza como programa de cierre; no se abre otro epic con el
mismo resultado. Los IDs PM existentes conservan historia y evidencia. Nuevas tareas se
registran en backlog sin fecha ficticia; supervisor humano explícito; la ejecución no se activa por asignación.

### Dependencias y secuencia

#### Primera iteración AC-02: continuidad de evidencia y economía de agentes

El diagnóstico del 20/09 comparó tres corridas medidas: GW5 6/25 sujetos verificados con
137921 tokens de entrada y 4506 de salida; GW4 6/25 con 146154/4802; otra de GW4 llegó
a 11/25 con 348056/7010 y excedió el presupuesto de 160000 tokens. Son corridas, no tres
GWs passing. El foco abarca hasta 25 jugadores de 12–14 clubes mientras la política permite
8/5/4 búsquedas y 10/8/6 documentos según slot. Por ello el límite de discovery sigue siendo
una hipótesis de insuficiencia que requiere medir cobertura por club, no una razón para reducir
el gate de 90/80 o inventar sujetos revisados.

Primera entrega desplegada en la release `1accdc4`: el manifiesto puede adjuntar hasta ocho pistas
de documentos verificados de la última corrida del mismo ciclo, de máximo 36 horas. El worker
revalida cada página y el importador conserva el fetch independiente; una pista sola jamás
cuenta como cobertura. La cobertura por club queda registrada en nuevos briefs v2 para
diagnosticar discovery. Las pruebas ejercen reutilización, expiración y agregación por club.
Falta medir una pareja real broad→refresh/final; no se atribuye aún ahorro ni mejora del gate.
La [release y sus límites](../../decisions/2026-27/release-20260920-1accdc4.md) son
evidencia de AC-01.1/01.3, pero AC-01.2 y el rollback efectivo siguen pendientes.

Routing: mantener Codex Researcher Luna y Strategist/Critic Terra mientras se mide una línea
base real. La suscripción registra tokens, pero `estimated_cost_usd=null`, por lo que no equivale
a costo cero ni ofrece un costo marginal comparable. OpenRouter no tiene credencial provisionada
en el VPS. Como escenario, Gemini 3.8 Flash figura a USD 0.75/M input y 3.75/M output; aplicado
a los tokens reportados de GW5 serían ~USD 0.12 sólo de modelo, más búsquedas (p. ej. cinco a
USD 0.005 serían ~USD 0.025). Esto no es factura ni predicción fiable: tokenización, tool calls,
calidad y límites podrían diferir. Antes de cambiar, hacer shadow pareado con los mismos
manifiestos, techo de gasto, 90/80, latencia, costo total por sujeto verificado y cero
violaciones de evidencia. La decisión de proveedor se toma por costo de resultado válido.
Precios consultados: [modelo](https://openrouter.ai/google/gemini-3.8-flash) y
[web search](https://openrouter.ai/docs/guides/features/server-tools/web-search).

1. AC-01 estabiliza la base; AC-02 y la preparación de AC-06/07 pueden desarrollarse
   independientemente. Elegir destinos precede a pruebas externas.
2. AC-03 integra la evidencia de AC-02 y la instalación C1 existente. AC-04 y AC-05 completan
   los adapters sobre contratos estables; AC-05 conserva dependencia de verificación R2.
3. Los ensayos longitudinales AC-02/04/05/08 comienzan en la primera GW elegible y acumulan
   jornadas reales. Antes de estabilizar el contrato, verificar qué evidencia sobrevivirá al cambio.
4. AC-09 prepara el expediente sin habilitar nada. Activación por capacidad sólo después de
   pruebas aplicables y decisión humana. AC-08 certifica el resultado posterior a promoción.

Supabase sólo admite una dependencia estructurada: las dependencias adicionales de esta sección
se conservan en las descripciones. No crear un ciclo entre promoción previa y aceptación posterior.
La fecha histórica del epic, 15 de octubre, no se renueva ni se convierte en garantía de cierre.
Con GW6 el 10 de octubre, la evidencia faltante de tres GWs no cabe necesariamente en esa fecha;
la planificación de fechas requiere compromiso nuevo, sin rebajar requisitos.

### Depuración de planificación anterior

Esta tabla registra disposición de documentos y correspondencia de alcance, no estados vivos PM.

| Documento/registro anterior | Disposición | Destino del pendiente |
| --- | --- | --- |
| Motor v1 cerrado; readiness todavía draft | Readiness histórico, no backlog nuevo; conservar evidencia y siete tareas spec_v1 cerradas | Calibración/claims en `FPL-MODEL-CALIBRATION-2026` y su subtarea existente |
| WP-001 runtime, WP-002 control plane | Plan inicial sustituido; no declararlos aceptación autónoma | AC-01/03/06/07; cutover separado |
| WP-004 research | Plan inicial sustituido; calidad todavía insuficiente | AC-02 |
| WP-006 browser | Plan inicial sustituido; contratos conservados | AC-04/05 |
| WP-007 observabilidad | Plan inicial sustituido; dashboards instalados no prueban delivery externo | AC-06 y costos AC-02 |
| WP-008 rollout | Plan inicial sustituido; no reusar taxonomía histórica A1 para alineación | AC-08/09 |
| WP-003 datos y WP-005 decisión | Conservar completed como instalación histórica | Continuidad y aceptación nuevas en AC-03/08 |
| C1 `FPL-HV1-07` done | Precisar título como instalación de orquestación/contratos, sin reabrir ni atribuir driver productivo completo | AC-04/05/08 |
| Diez tareas PM abiertas | Ninguna tiene evidencia de cierre integral; reutilizar ocho en revisión y conservar modelado/claims sin duplicados según mapa | No cancelar ni marcar done para limpiar el tablero |
| `FPL-HV1-02` PostgreSQL | Línea de persistencia separada del camino crítico | Writer operativo SQLite permanece hasta cutover aprobado |

### Recibo de organización PM — 20 de septiembre de 2026

Epic conservado: `632a0e4c-e44e-4f98-b3ee-a1e2e357b63f`.
Nuevas tareas, registradas en backlog bajo supervisión de Julián:

- AC-01: `6aea32b2-b1d7-4dfb-9b80-fc92352da8af`.
- AC-03: `7a0397a3-56c5-46da-9567-db28007a113a`.
- AC-09: `4a5e96b3-c7a9-4d8b-979a-0ce3ca65643b`.

Ocho tareas abiertas existentes revisadas; C1 cerrado sólo aclara su título/alcance.
Siete tareas revisadas sin fecha pasan de active a backlog conservando estado de avance;
no se pausa ningún servicio por ese cambio PM. Modelado y su subtarea se preservan.
Ninguna tarea se cancela, borra o completa. Las seis specs iniciales sustituidas conservan
el contenido histórico. Cinco referencias a actas ausentes en el checkout se señalan como
tales, sin fabricar evidencia ni mantener enlaces rotos.

### Verificación y definición de terminado

Por entrega: AC, prueba proporcional, SHA, entorno, fecha, artefacto y resultado; para código,
suite exigida por AGENTS y checks de despliegue pertinentes. Fixtures prueban comportamiento,
probes prueban lectura/DOM, y pruebas reales prueban guardado: no intercambiar esas etiquetas.

Cierre integral: AC-01…09 satisfechos, autoridad explícita, alertas y restore externo probados,
una GW completa sin rescate y evidencia separada de capacidades no ejercidas. Modelo/policy
permanecen versionados; candidato no se auto-promueve. Si falta evidencia, se conserva pendiente.
No se exige cambiar el writer a PostgreSQL ni un resultado deportivo positivo para acreditar
funcionamiento; tampoco se usa doctor verde o cantidad de tests como sustituto de aceptación.

## Plan C1–C5 del 14 de septiembre — histórico, sustituido

El contenido siguiente conserva contratos y contexto de aquella revisión. Sus fechas, prioridades,
contadores y rutas de ejecución no son planificación vigente; usar la sección del 20 de septiembre.

### Guía anterior de cierre autónomo — 14 de septiembre de 2026

Esta sección sustituye como guía de ejecución los checkpoints y gates narrativos históricos
inferiores. La spec [Autonomous Harness v1](10-autonomous-harness-v1.md) conserva la arquitectura;
este documento concentra el cierre operativo. El código de readiness y su `required_for`
determinan elegibilidad. Este plan documental no modifica controles ni constituye promoción.
La autorización de Julián en esta sesión cubre documentación y actualización PM antes de ajustes.

### Resultado y definición de terminado

Operar la temporada con el bundle predictivo aprobado, sin intervención humana rutinaria:
captura → research → decisión/validación → ejecución única → verificación → settlement oficial
→ review → memoria del siguiente ciclo. El operador escala excepciones con contexto accionable.
La investigación de modelos continúa en candidatos separados; entrenamiento, aceptación de una
propuesta y activación de un modelo son estados distintos. No se exige fabricar una lección o
mejora positiva cuando la evidencia concluye «sin cambio».

El cierre integral exige: requisitos técnicos aplicables A3 satisfechos, autoridad registrada,
ejecutor productivo R2/R3 verificado, alertas externas y recuperación off-host comprobadas,
y una GW completa posterior a la promoción sin comandos de rescate ni empuje desde el chat.
Conservar las tres GWs independientes exigidas por los gates. Una GW de aceptación sin
transferencia/chip no acredita por sí sola esas capacidades: adjuntar su evidencia específica.
Una prueba DOM read-only tampoco demuestra que el guardado real funciona.

### Baseline observado y faltantes

Corte VPS 2026-09-14 23:12 UTC / 18:12 Colombia, runtime
`191d809fd3745c0fb8bb24a4e35e3b2f45902413`, v0.7.0.
Consultas: `mova readiness`, `mova execute status`, `mova harness scorecard` y `mova status --json`.
Readiness: 16 pass, 9 pending, 0 blocked; elegibilidad A0. Estado healthy y controles shadow/A0,
kill switch activo, writes apagado, compliance pendiente. No es una nueva corrida de doctor.

| Frente | Evidencia al corte | Faltante para cierre |
| --- | --- | --- |
| Salud/recuperación host | operations 7/7; cinco escenarios host aprobados históricamente | Revalidar revisión, doctor y rollback tras cada despliegue |
| GW4/GW5 | GW4 aún sin finished+data_checked en consulta 23:10 UTC; GW5 preliminary; review GW4 not_found | Esperar flags oficiales, refrescar y conciliar; investigar desfase si persiste tras cadencia |
| Research | 2 GWs medidas, 0 passing | Corregir cobertura/evidencia; tres GWs válidas según gate, sin rebajar umbrales |
| Costos agentic | Overrun histórico 355066/160000, reviewed/reduce_scope; mes dentro de presupuesto | Follow-up equivalente dentro de límite y cierre auditado del overrun |
| R2 capitanía / XI-banca | 0/3 cada uno con contrato actual; entrypoint sólo capitanía | Ensayos por GW/capacidad/versión, integración y verificación del guardado |
| R3 transfers/hits/chips | Contrato implementado, 1/3, entrypoint off | Ensayos restantes, ejecución productiva verificada y promoción separada |
| Cierre de ciclo | manual_verified/latch pendiente; feedback 3 propuestas, 0 evaluaciones, 0 lecciones | Registro supervisado normalizado y continuidad automática hasta memoria |
| Alertas | journald/local_only, sin destino/owner ni live ping | Destino autorizado, entrega probada, acuse y escalamiento |
| PostgreSQL | Paridad/roles pass; 3/3 GWs | Cutover de writer conserva su tarea independiente; no bloquea A2/A3 según required_for actual |
| Off-host | Sin configurar, sin restore | Destino/owner, copia cifrada, timer y restore de ocho checks |
| Autoridad | A0; compliance y promoción pendientes | Resolver decisión documentada y activar por capacidad sólo tras evidencia |

Off-host no aparece como requisito técnico A2/A3 (`required_for=[]`), pero sí es criterio de
entrega integral de este plan. Mantener esa distinción visible; no cambiar el gate por editar PM.
Los ensayos R2 de GW3 pertenecen a una versión anterior y no se cuentan para la actual.

### Hoja de ruta y tareas canónicas

Responsables de implementación: por asignar; no se infiere una asignación humana desde este plan.
Las dependencias múltiples se conservan en esta tabla y en las descripciones PM.

| Etapa | Trabajo / work_key existente | Dependencias | Criterio de salida |
| --- | --- | --- | --- |
| C1 — Cierre verificable | `mova-fpl-v0.6.4-manual-verified` | Contrato de autoridad vigente | Desplegado: `manual-verified-execution-v2` importa pre/post-state, autorización y hashes; el latch impide nuevas acciones. Falta ejercerlo con evidencia real elegible |
| C1 — Continuidad del ejecutor | `FPL-HV1-07` | Cierre anterior, R2/R3 | Desplegados scheduler y closeout automático: plan autorizado, claim, driver y verifier son idempotentes; el timer construye el cierre desde el ledger supervisado o nativo, candidato único y batch causal. Falta una GW elegible que pruebe la cadena productiva completa |
| C2 — Agentes fiables | `FPL-AUTO-RESEARCH-PIPELINE` | Datos frescos y contrato de evidence | Fetch/locator/TTL/cobertura válidos, 3 GWs passing; Strategist/Critic terminan dentro de cadencia; follow-up de costo validado; intervención conserva autoridad acotada |
| C3 — Alertas | `FPL-AUTO-ALERTING` | Destino y owner autorizados | Configuración + live ping para fingerprint vigente, recepción/acuse y prueba de retry/dedup |
| C3 — Respaldo | `FPL-AUTO-OFFSITE-BACKUP` | Destino y owner autorizados | Copia cifrada fuera del VPS, retención/timer y restore aislado 8/8; excluir perfil browser y CODEX_HOME |
| C4 — R2 | `FPL-HV1-07D` | C1; contrato estable | Capitanía 3/3 y lineup 3/3 por GWs distintas; guardado supervisado y reload correctos; entrypoint lineup verificado |
| C4 — R3 | `FPL-HV1-07E` | C1, verificación R2, política R3 | 3/3 por contrato; reconciliar FT, precios, hits e inventario chips; guardado y resultados ambiguos probados; habilitación sólo con autorización A3 |
| C4 — Evidencia longitudinal | `FPL-AUTO-SHADOW-DRILLS` | C1/C2 y ensayos C4; C3 para entrega | Matriz por GW, versión, capacidad y SHA; cero duplicados/huérfanos; aceptación real hasta review y memoria |
| C5 — Promoción y aceptación | `FPL-HARNESS-V1` | C1–C4, compliance | Preparar expediente A2 y luego A3, registrar límites y aprobación; una GW completa sin intervención rutinaria; aceptación integral documentada |
| Paralelo — Persistencia | `FPL-HV1-02` | Paridad/roles/3 ciclos ya pass; backup/restore para cutover | Ensayar y aprobar cambio de writer/rollback por su contrato, sin bloquear artificialmente el camino operativo |

Orden de implementación: C1 primero; C2 y C3 pueden avanzar en paralelo. Iniciar ensayos C4
en la primera GW elegible tras fijar contratos. C5 comienza sólo con los gates aplicables.
GW5–GW7 son una ventana candidata de tres jornadas, no un compromiso ni evidencia anticipada:
si una jornada no pasa, se extiende la ventana. No reetiquetar pruebas de una versión previa.
El deadline PM histórico del epic (15 de octubre) sigue siendo una fecha objetivo, no una
certificación de autonomía ni permiso para omitir pruebas. No se inventan horas o fechas de subtareas.

### Evidencia mínima por entrega y por jornada

- Por cambio de código: requisito, diff, pruebas cercanas y suite exigida por AGENTS; compileall
  y Compose cuando corresponda; SHA desplegado/imagen, doctor, controles y rollback.
- Por GW: flags oficiales, corte de datos, manifest/bundle, research y costo, envelope/validator,
  clase de riesgo y autorización, pre/post-state sanitizado, intento único y resultado tras reload.
- Después de finished+data_checked: scorecard causal sólo si existió batch predeadline,
  settlement conciliado, review y memoria de la siguiente GW. «Sin hipótesis suficiente» es válido;
  no introducir resultados retrospectivos como entrenamiento o evidencia predeadline.
- Excepciones: auth expirada, datos stale, research incompleto, presupuesto agotado o save ambiguo
  deben producir estado terminal explícito, alerta y reanudación segura; nunca retry ciego.
- Promoción: fijar límites de hits/chips, ventanas, fallback y tratamiento de conflictos en policy
  versionada; resolver compliance con evidencia vigente. Ningún umbral deportivo se inventa aquí.

### Contrato del closeout automático

El cierre `mova-fpl-autonomous-closeout-v1` elimina la redacción manual rutinaria sin rebajar
trazabilidad. Es elegible únicamente cuando existe `decision_runs.executed_verified` y una fuente
de ejecución verificada: `web_executions.verified` para el registro supervisado o
`execution_attempts.verified` para el ejecutor nativo. Todos sus checks deben pasar, los artefactos están dentro del root privado y
reproducen sus hashes, y el fingerprint ejecutado identifica un solo candidato en el envelope
sellado más reciente. También exige un `team_state_snapshot` válido, posterior a la ejecución y
con el mismo fingerprint, para no sintetizar banco, transferencias libres ni chips. El comparador
siempre es `do_nothing` del mismo envelope. Nombres,
posiciones, precios al corte, xP y P60 provienen de un batch `approved` completo con
`cutoff_at <= deadline`; el resultado proviene de FPL con `finished + data_checked`.

El timer de analytics prueba este cierre después de reconciliar datos finales y antes del reviewer
causal. La clave `autonomous-closeout:<season>:gw<N>:v1` hace el replay idempotente. Si falta una
precondición o la ejecución humana se apartó del envelope, abre incidente P2 y conserva el ciclo
sin settlement; exige evidencia explícita, no reconstrucción retrospectiva. Transferencias, chips
y número de transferencias pagadas se propagan al motor, y `hit_cost = hits × 4` se concilia contra
los puntos netos oficiales.

Readiness publica dos gates separados: `AUTONOMOUS_CLOSEOUT_INSTALLED` es requisito técnico A2/A3
y verifica contrato + scheduler; `AUTONOMOUS_CLOSEOUT_LIVE_PROVEN` exige al menos una GW completa,
pero es evidencia de aceptación integral (`required_for=[]`) para no crear un requisito circular de
promoción. Que el primero pase nunca sustituye al segundo ni concede autoridad.

### Seguimiento y límites del plan

Supabase refleja trabajo y evidencia, no autoridad. Reutilizar IDs/work_keys abiertos, conservar
las tareas de implementación terminadas y no tocar snapshots `spec_v1` del motor histórico.
Actualizar descripciones, criterios y dependencias; no cerrar una tarea por escribir este plan.
La tarea padre asume C5; el ejecutor asume continuidad post-GW y la tarea longitudinal su aceptación.
Las mejoras de modelado, nuevos datasets y auto-modificación quedan fuera de este cierre operativo.

## Archivo histórico — no usar como política ejecutable vigente

Los apartados siguientes preservan decisiones y evidencia con su fecha original. Las referencias
a A1 para alineación, equivalencias de rehearsals y contadores de agosto están superadas por la
taxonomía R2→A2 / R3→A3 y los gates por versión descritos arriba. No rebajan requisitos actuales.

## Veredicto

**SHADOW CONTROL PLANE ACTIVE · NOT READY FOR FPL WRITES.**

El runtime reproducible, plano de control, scheduler, collector, modelos, auditoría,
backup y ejecutor browser aislado ya corren en el VPS. Los gates permanecen cerrados en
`shadow`, `A0`, `compliance=pending`, `kill_switch=true` y `browser_writes=false`.
El perfil fue autenticado bajo supervisión, corresponde a `losmillosFPL` / `entry_id=3609854`
y sobrevivió una recreación controlada del contenedor. Faltan completar research/alerting y
acumular evidencia antes de evaluar cualquier escritura externa.

La evidencia verificable del corte está en
[07-deployment-evidence.md](07-deployment-evidence.md). La matriz inferior se conserva
como baseline del diagnóstico previo al despliegue.

Desde el 30 de agosto, el veredicto también es máquina-legible mediante `mova readiness` y
`/api/v1/readiness`. El corte vivo del 31 de agosto conserva A0 técnico: 15 de 25 gates pasan,
10 esperan evidencia temporal o una integración externa autorizada y ninguno está bloqueado por
un fallo abierto. Esto no reemplaza esta política ni concede autoridad. Ver
[acta HV1-09M](57-hv1-09m-final-runtime-closeout.md).

## Checkpoint vigente — 2026-08-22

| Área | Evidencia | Estado |
| --- | --- | --- |
| Browser dedicado | Chromium normal supervisado; agent-browser se adjunta por CDP interno | ready para lectura |
| Identidad FPL | `/en/my-team` contiene `losmillosFPL` y `entry_id=3609854` | verified |
| Persistencia auth | recreación de contenedor conservó acceso autenticado | verified |
| Exposición | noVNC sólo `127.0.0.1:6080`; CDP sólo loopback del contenedor | verified |
| Escritura FPL | shadow A0, compliance pendiente, kill switch activo | blocked por diseño |

## Matriz previa al despliegue (corte 2026-08-21)

| Área | Evidencia | Estado |
| --- | --- | --- |
| Motor/reglas | 631 tests rápidos + 2 slow; decisión viva válida | ready |
| Datos históricos | 253.890 filas, 10 temporadas, integridad y claves únicas | ready |
| Collector vivo | hash + semántica PASS; 600 players/380 fixtures al corte | ready, falta deploy/observabilidad |
| Modelos | minutes/points 1.1.0 cargan y tienen training de 10 temporadas | ready como baseline |
| Agente de noticias | contrato existe; efecto del LLM no está probado | shadow only |
| Estado privado FPL | skill manual probada; API pública insuficiente para PP/SP/FT | partial |
| Ejecutor browser VPS | no hay perfil FPL ni agent-browser dedicado | missing |
| VPS | capacidad y privilegios adecuados; Python host incompatible | ready para Docker |
| Git/deploy | local ahead 5; VPS/remote en `0105452` | blocked hasta sincronizar |
| Persistencia operativa | no existe `ops.db`; SQLite host 3.45.1 no cumple el gate WAL ≥3.51.3 | missing, requiere runtime Docker fijado |
| Scheduling | cron activo, systemd disponible; no existe timer MOVA | missing |
| Observabilidad | trace analítica parcial; no hay metrics/alerts/dashboard | missing |
| Compliance | términos vigentes plantean riesgo de automatización | blocker de write |

## Inventario VPS observado

Corte remoto: `2026-08-21 15:46 UTC`, inspección read-only.

| Recurso | Estado observado | Implicación |
| --- | --- | --- |
| Host | Ubuntu 24.04.3, 2 CPU, 7.8 GiB RAM, 4.4 GiB disponibles | cabe un runtime austero; necesita admission gates |
| Disco | 96 GiB totales, ~68 GiB libres | suficiente para DB/artifacts con retención y alertas |
| Runtime | Docker 29.1.3, Compose 2.37.1, systemd 255 | base aprobada para WP-001 |
| Carga existente | 11 containers; Docker usa ~12.9 GiB images, ~2 GiB volumes | no instalar stack pesado de observabilidad |
| Persistencia | `/opt/orbital/backups` privado; no restic/borg/rclone | backup local posible, off-host pendiente |
| Scheduling | cron y systemd activos; watchdog Orbital cada 30m | adoptar units/timers, no root crontab |
| Red | servicios internos mayormente en loopback; Caddy en 80/443 | MOVA no requiere puerto público |
| Repo | MOVA no está clonado; acceso Git sí funciona | release debe sincronizar SHA y artifacts ignorados |

No se modificó el host durante esta inspección.

## Gates de release

### G0 — Spec approved

- arquitectura y riesgos revisados por Julián como owner, con evidencia técnica registrada;
- Q-01..Q-04 resueltas o aceptadas;
- threat model y ownership de incidentes asignados;
- ningún cambio operativo mezclado con la aprobación.

### G1 — Runtime reproducible

- Git remoto contiene el commit aprobado y VPS despliega exactamente ese SHA; hoy el remoto
  está cinco commits detrás del checkout local;
- imágenes por digest con Python 3.13/CBC, SQLite ≥3.51.3 y lockfiles;
- startup gate demuestra `sqlite_version()` corregida; ningún job productivo usa el binario
  SQLite 3.45.1 del host;
- volumes, backups, healthchecks, límites y restore drill probados;
- suite rápida y smoke live read-only pasan dentro del contenedor.

### G2 — Control plane observable

- `ops.db` migrado con WAL, foreign keys, constraints, permisos y backup consistente;
- tick idempotente, `flock`, ledger, outbox y replay probados;
- dashboard Now/Operations y alertas P0/P1 con acuse;
- caos básico: reboot, API caída, DB caída, snapshot inválido.

API, PostgreSQL, browser, outage combinado y reboot real tienen evidencia viva. El reinicio
autorizado del 31 de agosto cambió el boot ID, reanudó el scheduler y pasó 11/11 checks sin mutar
el estado FPL. `HOST_RECOVERY_DRILLS_PROVEN` está completo 5/5. G2 conserva como pendientes de
operación el destino externo de alertas y el backup cifrado off-host; no son fallos del runtime.

### G3 — Shadow season loop

- mínimo 3 GWs completas o equivalente de rehearsals con todos los estados;
- cero jobs huérfanos, decisiones irreproducibles o alertas perdidas;
- research signals y atribución funcionan, pero LLM no altera producción;
- search citations se refetchean y sellan; ningún claim aceptado depende solo de metadata
  del provider;
- budgets, retry layers, wall timeout, redaction y `cost_known` pasan drills;
- deadline drill acelerado demuestra freeze, hard stop y recuperación.

### G4 — Supervised execution

- compliance gate registrado;
- browser dedicado autenticado por Julián, sin secretos automatizados;
- fixtures DOM y tests contractuales;
- al menos 3 ejecuciones supervisadas A1/A2 con reload y evidencia;
- kill switch y recuperación de ejecución ambigua ensayados.

### G5 — Guarded

- A1 automático estable al menos 3 GWs;
- cero discrepancias post-reload y cero duplicados;
- A2 habilitado separadamente, con sensitivity gate y límites;
- toda falla conduce a estado verificado anterior antes de hard stop.

### G6 — Autonomous

- temporada estratégica, chips y FTs reconciliados;
- A3 aprobado explícitamente;
- hits/chips pasan margen, robustez, fuente y ventana reforzados;
- revisión mensual de desempeño y seguridad conserva facultad de rollback.

No se salta un gate por cercanía al deadline.

## Política de promoción del agente

Los hallazgos actuales no justifican control productivo: 18 intervenciones shadow tuvieron
media negativa y el intervalo incluye cero; pruebas named/anonymized muestran fragilidad.

Para salir de shadow:

1. causalidad y contaminación revisadas;
2. señales siempre citadas y sin confabulaciones materiales;
3. efecto local pareado, no total de temporada;
4. muestra predefinida y criterio registrado antes de evaluarla;
5. no degradación de factibilidad, calibración o incidentes;
6. aprobación humana de la nueva policy version.

Una propuesta de memoria o regla nunca se auto-promueve. Se crea candidata y pasa por el
mismo proceso.

## Reglas de hits y chips

El diseño no fija ahora los umbrales deportivos: obliga a versionarlos y medirlos. Como
gate mínimo:

- hit: ganancia neta después del coste > margen configurable en escenarios base/bajo;
- chip: ventaja vs no-chip en horizonte, ventana legal e inventario confirmados;
- transfer: beneficio robusto a minutos/fixture y reconciliación exacta de SP/FT;
- cualquier conflicto de disponibilidad significativo bloquea A3;
- máximo una ejecución irreversible por revisión y GW.

## Rollback

| Cambio | Rollback |
| --- | --- |
| modelo | volver al último `production` por hash; no reentrenar de urgencia |
| policy/prompts | pin anterior; revisions existentes permanecen inmutables |
| app | imagen digest anterior y migration compatibility verificada |
| browser | deshabilitar executor y pasar a supervised/manual |
| nivel de autonomía | bajar A3→A2→A1→A0 en control plane |
| sistema completo | kill switch global; conservar último equipo verificado |

El rollback de software no intenta revertir automáticamente una transferencia o chip ya
confirmado. Esos efectos son del juego y se tratan como incidente/estado nuevo.

## Readiness checklist por GW

- [ ] deadline oficial confirmado y countdown correcto;
- [ ] snapshots obligatorios frescos, válidos y sellados;
- [ ] team state reconciliado, incluidos PP/SP/FT/chips;
- [ ] fuentes de noticias cubiertas y conflictos resueltos/declarados;
- [ ] modelos/rules/config/prompt hashes permitidos;
- [ ] decisión factible y sensitivity gate verde;
- [ ] modo, compliance y action level permiten la acción;
- [ ] browser sano y sesión corresponde a `entry_id=3609854`;
- [ ] no existe ejecución previa ambigua;
- [ ] hay tiempo para ejecutar y verificar antes de hard stop;
- [ ] alerta P0 tiene ruta de acuse disponible;
- [ ] kill switch probado y accesible.

## Decisión vigente

La implementación y operación `shadow A0` están activas. Sigue sin estar autorizada la
ejecución sobre FPL. Cualquier promoción requiere evidencia de los gates G3/G4, decisión
registrada sobre compliance y aprobación explícita separada.

## Estado de cierre — 31 de agosto de 2026

La construcción técnica del harness read-only A0 está cerrada. “Cerrada” significa que collector,
modelos, estado privado, research, decisión multirol, validación, memoria, costos, PostgreSQL
shadow, observabilidad, backups locales, browser aislado y recuperación host tienen contratos,
runtime y evidencia verificable. No significa que el producto haya recibido autoridad para
escribir en FPL.

Los diez gates pendientes se dividen por causa y no deben mezclarse en una sola cifra de progreso:

| Grupo | Gates | Estado / desbloqueo |
| --- | --- | --- |
| Settlement | `GAMEWEEK_INPUTS_READY` | automático al cerrar oficialmente GW2 y refrescar GW3 |
| Longitudinal | research, capitanía, lineup, R3 y tres ciclos PostgreSQL | acumular tres GWs distintas; repetir GW3 no cuenta |
| Integración externa | canal/live-ping de alertas y backup/restore off-host | Julián elige destino y owner; luego se provisionan secretos root-only y se prueba |
| Autoridad | compliance y promoción A1/A2/A3 | decisión humana separada después de que pasen los gates técnicos aplicables |

Mientras tanto, el estado operacional esperado es `not_ready` con cero blockers: el scheduler debe
seguir recolectando y produciendo evidencia en A0. Un pending longitudinal no abre incidente; una
falla de salud, integridad, cola o frescura sí debe hacerlo.
