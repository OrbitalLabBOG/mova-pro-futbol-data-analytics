---
type: project
name: "MOVA FPL Autonomous Operator 2026/27 — Readiness and Rollout"
created: 2026-08-21
updated: 2026-09-14
tags: [mova, fpl, readiness, rollout]
status: active-shadow
---

# Readiness y rollout

## Guía vigente de cierre autónomo — 14 de septiembre de 2026

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
| C1 — Cierre verificable | `mova-fpl-v0.6.4-manual-verified` | Contrato de autoridad vigente | Implementado localmente en `manual-verified-execution-v2`: importa pre/post-state, autorización y hashes; latch impide nuevas acciones; falta desplegar y comprobar con evidencia real elegible |
| C1 — Continuidad del ejecutor | `FPL-HV1-07` | Cierre anterior, R2/R3 | Ruta de closeout automático implementada: el timer analítico construye package sólo desde ejecución verificada, candidato único del envelope y batch causal; falta desplegarla y ejercerla en una GW elegible. Scheduler conecta además plan autorizado, claim, driver y verifier; replay/restart/estado ambiguo no duplican acciones |
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
trazabilidad. Es elegible únicamente cuando existen `decision_runs.executed_verified` y
`web_executions.verified`, todos sus checks pasan, los artefactos están dentro del root privado y
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

- arquitectura aprobada por Julián y Buitra;
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
