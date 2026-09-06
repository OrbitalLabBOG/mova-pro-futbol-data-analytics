---
type: docs
name: MOVA Fantasy Fútbol Data Analytics
updated: 2026-09-06
status: active
tags: [mova, fpl, runtime, operations]
---

# MOVA Fantasy Fútbol Data Analytics

Motor operativo y analítico para gestionar el equipo `losmillosFPL` durante la temporada
Fantasy Premier League 2026/27. El repositorio contiene únicamente el producto FPL vigente:
collector, almacén causal, modelos de minutos y puntos, optimizador MILP, control plane del
VPS y contratos de operación segura.

El stack autónomo está desplegado en modo `shadow / A0`: puede recolectar, modelar, decidir
y auditar, pero los cambios en la cuenta continúan bloqueados por controles explícitos.
El cockpit read-only comparte un único contrato entre CLI y API. Su dashboard ejecutivo público
sólo expone tres indicadores humanos; diagnóstico, métricas y JSON permanecen en loopback.
Supabase sólo refleja seguimiento PM y nunca recibe estado operativo.

## Versiones y última comprobación

Verificado el **5 de septiembre de 2026, 17:13 Colombia**: doctor FPL con
**24 PASS, 0 WARN, 0 FAIL**; cockpit saludable, sin incidentes críticos ni
violaciones del workflow. Continúan ocho incidentes abiertos, GW4 preliminar,
A0/shadow y preparación autónoma pendiente. El corte detallado anterior se
conserva abajo con su fecha; no representa un monitor en vivo.

| Componente | Versión / revisión | Alcance |
| --- | --- | --- |
| Motor FPL desplegado | v0.7.0 · `dea98e2` | Predictores 1.1.0; `season_value` 1.0.0 como challenger shadow |
| Código integrado en GitHub al corte | `19e066b` · PR #40–43 fusionadas | Motor, acta, benchmark y tracking |
| MLflow desplegado | `mlops-v1.0.0` · `19e066b` | Servicio independiente con MLflow 3.16.0 |

Los commits posteriores al motor añaden documentación, benchmark y el servicio
MLflow separado; no implican una promoción del predictor ni un nuevo despliegue
FPL. Para desarrollar, partir de `origin/main` en un worktree limpio y revisar
`git status`: los checkouts de experimentos antiguos pueden conservar trabajo local.
GitHub conserva código y contratos; los binarios, credenciales y evidencia privada
permanecen en sus almacenes operativos.

## Estado verificado del despliegue (corte detallado anterior)

Corte: **4 de septiembre de 2026, 22:29–22:45 America/Bogota**
(`2026-09-05T03:29–03:45Z`). Es una observación del VPS, no un monitor en vivo.
Checkout e imagen coinciden en **v0.7.0**, SHA
`dea98e20db44b05da7b426d0b4476f1cd5fca928`; el checkout desplegado está limpio.

| Superficie | Evidencia observada |
| --- | --- |
| Doctor | **24 PASS, 0 WARN, 0 FAIL**, exit 0; contrato `mova-fpl-operator-v1`, versión 1.0 |
| Procesos | API y PostgreSQL healthy; ocho timers activos; servicios programados sin resultado fallido; heartbeat fresco |
| Datos y modelos | Bases íntegras, artefactos presentes, cuatro fuentes saludables y servicio analítico consultable |
| Persistencia | SQLite es writer del harness; PostgreSQL 17.11 es shadow de ese ledger y writer del data service; paridad del último import sellado: 57 tablas, 0 fallos (no incluye automáticamente los nuevos eventos) |
| Cuenta y browser | Snapshot privado válido de 15 jugadores dentro del umbral de frescura; browser detenido, perfil persistente presente |
| Autoridad | `shadow / A0`, `kill_switch=true`, `browser_writes=false`; elegibilidad técnica A0 |
| Seguridad operativa | `overall_status=healthy`, `safety=safe_to_wait`; cero P0/P1 y ocho P2 abiertos |
| Preparación autónoma | `not_ready`: **15/25 gates pass, 10 pending, 0 blocked**; scorecard `pending` |
| Cockpit | «Operación estable con pendientes», `attention_required`; workflow sin violaciones |
| Respaldo y alertas | Backup local reciente; backup cifrado off-host sin configurar; alertas sólo en journald, sin destino externo ni owner |

El ciclo objetivo es **GW4**, fase `baseline`, con deadline registrado para el
**12 de septiembre, 07:30 Colombia**. Sigue `preliminary`: GW3 no está asentada y aún
quedan nueve partidos sin comenzar. Research y deliberación del ciclo están pendientes;
envelope y preflight terminan bloqueados por policy y ejecución queda `skipped_policy`.
Esto no equivale a un fallo de infraestructura ni autoriza promover decisiones.

El fallo del watchdog observado durante la mañana ya no aparece en el doctor actual.
Eso no demuestra que se haya implementado el cierre manual previsto para v0.6.4:
v0.7.0 incorpora el laboratorio analítico, no ese cierre manual. Persisten ocho incidentes P2 `Shadow decision falló`,
abiertos entre 12:30 y 13:15 Colombia. El log del último muestra un HTTP 503 en el
historial público del equipo tras cinco intentos; esa evidencia no atribuye la misma
causa a los otros siete. `status` no reporta jobs fallidos en su ventana de 24 horas,
pero los incidentes siguen abiertos y deben revisarse por separado.

La salud del servicio analítico no acredita calidad predictiva: la última scorecard
observada sigue siendo de GW2 y su evaluación de drift es `insufficient` por falta
de referencias. GW3 sólo se evalúa después de `finished + data_checked`.

Pendientes de producto y operación:

- Completar evidencia research en tres jornadas y ensayos browser: capitanía 0/3,
  XI/banca 0/3 y R3 1/3; los entrypoints de XI/banca y R3 siguen cerrados.
- Incorporar evidencia `manual_verified` para operaciones humanas con transferencias,
  cerrar el ciclo tras salvaguarda verificada y conciliar el contrato de autoridad.
  El importador actual sólo admite A1 sin transfers/chips; ejecución mapea R2 a A2
  y R3 a A3. La normalización prevista no está desplegada.
- Configurar y probar alertas externas, backup cifrado off-host y restauración;
  completar tres ciclos independientes para el shadow PostgreSQL (observado: 1/3).

Para renovar este corte, usar `mova doctor --json`, `mova status --json`,
`mova cockpit --json`, `mova readiness`, `mova harness workflow` y
`mova harness scorecard` desde el wrapper del VPS. Para un incidente, usar
`mova triage --incident-id ID --json` y revisar su evidencia. Estos diagnósticos
no ejecutan decisiones, no llaman agentes ni cambian permisos FPL.

El planificador `season_value` 1.0.0 está instalado en el comparador estratégico
shadow y completó una corrida real de GW4 con dos propuestas válidas. Conserva
los predictores `minutes/points` 1.1.0 y no sustituye la decisión seleccionada.
En ese corte propone reservar chips, mientras el control propone Bench Boost.
Consultar [experimento y acta de despliegue](experiments/season_value/README.md)
para resultados, hashes y límites de promoción.

El [benchmark interno de progreso](experiments/benchmark/README.md) consolida
el historial de investigación con comparaciones por protocolo, PVA-38 e incertidumbre.
[MLflow privado](docs/operations/mlflow.md) añade comparación interactiva, archivo
de modelos por hash y exportación revisable, sin promover modelos al runtime.

## Histórico para investigación

La [auditoría raw-history-v1](experiments/data_ground_truth/README.md) mide las diez
temporadas y añade 427 archivos fijados por commit y SHA-256, metadatos de identidad
y observaciones complementarias de partidos. Conserva staging separado del canónico:
la disponibilidad anterior al deadline todavía no está demostrada. Incluye cobertura,
reconciliación y comandos para repetir la medición antes de experimentar.
El gate G2 amplía a 1.161 archivos y genera 253.890 etiquetas con identidad oficial.
El archivo deportivo adicional abarca 17 temporadas desde 2009/10; sus claves de
partido se reconciliaron en G4 mediante clubes local/visitante; conserva anomalías
y procedencia separadas del entrenamiento productivo.
El gate G3 recupera además 2014/15: 24.876 filas, 38 jornadas y 380 partidos
reconciliados. G5 empaqueta 278.707 etiquetas de once temporadas, verificadas por
hash y separadas temporalmente: excluye 59 ceros de un partido aplazado en 2019/20.
G7 resuelve la identidad de las 10.428 apariciones con minutos de 2014/15 (100%);
quedan 46 jugadores sin apariciones con ID de temporada. Conserva equivalencias
verificadas cuando un código histórico cambió.
G6 completa 2015/16 con 24.741 observaciones, 723 jugadores y 380/380 partidos.
El paquete v3 suma **303.448 etiquetas de doce temporadas consecutivas**, 2014/15–2025/26;
verifica puntos y trece componentes contra totales finales de 2015/16. El manifiesto
permite fijar las entradas de cada experimento; no acredita replay predeadline.
G8 archiva y audita ocho bases históricas Differential, con material desde 2010/11:
permanecen fuera del entrenamiento por cobertura incompleta, nulos y discrepancias
con snapshots de totales. G9 recupera 10.353 apariciones de 2010/11 del SQL
anterior a esas transformaciones, pero detecta un jugador con minutos sin fila y
un universo sin no apariciones. Audita además siete snapshots BSON de 2015/16,
con cuarentena de identidades y resultados conflictivos. Son evidencia adicional,
no nuevas temporadas completas: el conteo validado sigue siendo doce temporadas.
G10 cruza los 380 partidos de 2010/11 con el archivo deportivo y localiza tres
diferencias de conteo de apariciones; conserva 524 candidatos de identidad sin
promoverlos. Las filas con minutos desconocidos siguen siendo desconocidas.
G11 recupera 268 códigos de fila deportivos con ID nativo, nombre completo y
partidos testigo: quedan 1.502 sin identidad; hay 179.847 observaciones deportivas
con identidad y minutos válidos, separadas de las etiquetas FPL y del runtime.
G12 verifica identidad para 502 jugadores / 10.164 apariciones FPL de 2010/11,
conservando los resultados originales. Quedan 189 filas sin identidad y la
temporada sigue fuera del paquete completo por el universo elegible pendiente.
G13 adquiere 5.978 archivos de historiales de jugador: el consenso alcanza 8.284
registros jugador-temporada de 2006/07–2024/25, con 6.308 claves adicionales.
Son totales retrospectivos con cobertura parcial, separados del benchmark por jornada.
G14 completa los 6.495 historiales de jugadores del inventario y alcanza 8.786
registros jugador-temporada. El paquete G14 **fpl-labels-v4**: corrige
cuatro valores en dos filas (Leno 2018/19 y Ferguson 2024/25), con evidencia directa
de CSV individuales y totales finales. Conserva 303.448 filas y doce temporadas;
6.934 totales coinciden tras la corrección. V3 y el runtime permanecen intactos.
G15 audita los 7.365 CSV individuales por partido del inventario 2016/17–2025/26.
El GT experimental vigente **fpl-labels-v5** contiene **303.126 filas de jugadores**
y conserva aparte 322 filas de Assistant Manager; añade una corrección de BPS
corroborada para Cucho Hernández. La auditoría explicita archivos repetidos o
incompletos, 15 filas adicionales con cero minutos/puntos y 78 fechas discrepantes.
Son doce temporadas de etiquetas retrospectivas, sin disponibilidad predeadline
acreditada; [G15](experiments/data_ground_truth/results-g15.json) no acredita
un replay causal completo ni una mejora del modelo.
G16 adquirió y auditó **7.837 snapshots bootstrap** (2021–2026), sin errores:
5.617.474 filas jugador-snapshot y 14.240 de managers separadas. Bajo la hipótesis
de reloj UTC, hay capturas dentro de 48 horas anteriores a los 38 deadlines de
cada temporada 2021/22–2025/26. Precio, club, posición y estado están presentes
en todas las filas de jugadores. Esto amplía estados históricos; no añade
etiquetas completas ni certifica disponibilidad predeadline. El detalle y hashes
están en [G16](experiments/data_ground_truth/results-g16.json).
G17 normaliza los 199 candidatos: 143.718 estados de jugadores y 320 de managers
separados. Las identidades admitidas de temporadas cerradas coinciden con v5;
dos cambios de código quedan en cuarentena. Se conservan 94.980 valores
desconocidos de selección y se mantienen deshabilitados entrenamiento y admisión
predeadline. [Resultados G17](experiments/data_ground_truth/results-g17.json).
G18 revisa identidades en los 7.837 snapshots: 5.391 claves temporada-elemento,
cuatro cambios de código, trece de nombre y cero colisiones de código entre
elementos dentro de temporada. Distingue tres casos de jugadores de una
sustitución de entrenador; no aplica alias automáticamente.
[Resultados G18](experiments/data_ground_truth/results-g18.json).
G19 corrobora tres alias de jugadores mediante continuidad del snapshot y fechas
de aparición; excluye el reemplazo de entrenador. Recupera dos estados de GW1
con códigos originales preservados: 143.720 estados de jugadores, 320 managers
y cero rechazos en los 199 candidatos. No habilita entrenamiento ni cambia GT v5.
[Resultados G19](experiments/data_ground_truth/results-g19.json).
G20 verifica los objetos Git de los 7.837 snapshots y contrasta 199 candidatos
con GH Archive: 198 horas adquiridas, una ausente (404), **164 deadlines con
publicación anterior corroborada** y 35 sin evidencia suficiente. Cubren
**117.195 estados de jugadores y 320 managers**. 2024/25 alcanza 38/38; 2025/26,
13/38. Son testigos temporales separados: G19 y GT v5 no se reescriben ni se
habilita entrenamiento. [Resultados G20](experiments/data_ground_truth/results-g20.json).
G21 recupera 32 testigos con capturas anteriores: **196/199 deadlines** corroborados,
con **38/38 en cada temporada 2021/22–2025/26**. El paquete seleccionado conserva
143.720 estados de jugadores y 320 managers; 141.853 estados de jugadores tienen
testigo. Las 32 capturas sustituidas son 4–36 horas más antiguas; se registran sus
cambios de precios, disponibilidad y ownership. Quedan sin testigo GW1–3 2026/27.
No se habilita entrenamiento ni replay completo.
[Resultados G21](experiments/data_ground_truth/results-g21.json).
G22 extrae reglas y calendarios de esos snapshots: **7.562 observaciones de jornada**,
141 cambios de deadline y **cero calendarios de fixtures**. Chips/scoring están
explícitos desde GW16 2024/25 en la selección; antes se conservan como ausentes.
Se documentan overrides que requieren interpretación, sin ejecutarlos como reglas.
[Resultados G22](experiments/data_ground_truth/results-g22.json).
G23 adquiere **254 versiones históricas de fixtures**, todas con 380 partidos,
y mide 2.020 cambios de kickoff y 387 de jornada. Para los 199 deadlines G21,
92 tienen una versión con commit previo de hasta 48 horas; esa fecha aún no
acredita publicación. 2025/26 solo tiene doce versiones y requiere una fuente
más densa. [Resultados G23](experiments/data_ground_truth/results-g23.json).
G24 incorpora 5.019 versiones de archivos Core y 28 del mirror. Reconstruye árboles
coherentes por commit, pero encuentra fechas sin zona, tres calendarios Core de
370 partidos y conflictos de jornada. Hay 749 fechas futuras raw pendientes de
reloj; el mirror aporta 209 observaciones futuras con zona en GW33–38. La brecha
no se declara cerrada. [Resultados G24](experiments/data_ground_truth/results-g24.json).
G25 audita 81 versiones del exportador Core y 6.552 comparaciones retrospectivas:
319 discrepan. Dos fechas bajo Premier League coinciden con partidos de Carabao
Cup documentados por los clubes. La hipótesis UTC no acredita identidad ni reloj
de origen; continúa sin admitirse ese calendario al GT.
[Resultados G25](experiments/data_ground_truth/results-g25.json).

G26 contrasta 207.363 etiquetas con calendarios finales de ocho temporadas. Las
78 diferencias corresponden a un único partido retrasado 30 minutos el día de
juego; se conservan ambos horarios y su historial sin sobrescribir GT v5.
[Resultados G26](experiments/data_ground_truth/results-g26.json).

G27 añade 199 versiones de fixtures de una nueva fuente fijada: 132 versiones
con identidad FPL completa para 2025/26. La unión con el archivo anterior aumenta
de 6 a 18 los deadlines con commit previo de hasta 48 horas; falta corroborar
publicación histórica. [Resultados G27](experiments/data_ground_truth/results-g27.json).

G28 corrobora publicación anterior al deadline para **26 calendarios 2025/26**
de la nueva fuente mediante GH Archive y ascendencia Git verificada. Cubren
5.015 observaciones futuras; quedan diez candidatos sin testigo y GW1–2 sin
candidato de esta fuente. [Resultados G28](experiments/data_ground_truth/results-g28.json).

## Empezar

Requiere Python 3.13.

```bash
python -m pip install -e '.[test]'
pytest -q
```

La suite por defecto no necesita bases ni modelos externos. La integración
MLOps pasó con **1.389 passed, 1 skipped y 79 deselected**, con CI aprobada en
PR #43. El corte del motor v0.7.0 tuvo 1.372 passed en PR #40.
Los seis fixtures que dependían del deadline del 4 de septiembre ahora usan un
reloj explícito; el gate productivo de deadline permanece activo.

Las pruebas que validan el dataset canónico y artefactos productivos se ejecutan
después de generarlos:

```bash
python -m mova_fpl.data.ingest --all
python -m mova_fpl.cli.train_minutes --holdout 2025-26
python -m mova_fpl.cli.train_points --holdout 2025-26
pytest -m integration_data -q
pytest -m slow -q
```

## Operación

La operación provisionada se ejecuta desde WSL por SSH como `ubuntu`. Dentro del
VPS, usar el wrapper con `sudo`; un checkout local no acredita la versión desplegada.

```bash
ssh ubuntu@72.60.245.2
sudo /usr/local/bin/mova cockpit --json
sudo /usr/local/bin/mova doctor
sudo /usr/local/bin/mova model status
sudo /usr/local/bin/mova harness scorecard
sudo /usr/local/bin/mova harness workflow
sudo /usr/local/bin/mova-mlflow ps
```

Esta es la ruta cotidiana de consulta. Para un incidente, seguir
[cockpit y triage](docs/operations/cockpit.md); para preparar y cerrar una jornada,
[operar una GW](docs/operations/gameweek.md). Entrenamiento, evaluaciones que
persisten resultados, cambios de autoridad y drills de recuperación tienen sus
procedimientos y argumentos auditados en los runbooks; no son pasos de un healthcheck.

| Necesidad | Procedimiento |
| --- | --- |
| Recolectar o diagnosticar fuentes | [Data service](docs/operations/data-service.md) |
| Entrenar, proyectar y evaluar | [Servicio analítico](docs/operations/analytics-service.md) |
| Preparar research y deliberación | [Contexto estratégico](docs/operations/strategic-research.md) |
| Promover o revertir modelos | [Mejora continua](docs/operations/continuous-improvement.md) |
| Comparar experimentos | [Benchmark](experiments/benchmark/README.md) y [MLflow](docs/operations/mlflow.md) |
| Desplegar, respaldar y recuperar FPL | [VPS](docs/operations/vps.md) |


El flujo de decisión conserva una sola autoridad y añade un lifecycle máquina:

```text
CycleManifest + memoria estratégica durable → modelos causales → matriz xP → MILP
  → do_nothing + baseline + alternativa
  → Validator determinista → DecisionEnvelope → acta + auditoría
  → Strategist + Critic acotados → Intervention shadow no aplicada
  → ExecutionPlan → apply-once ledger + driver R2 acotado + verifier
  → settlement → review → proposal → test gate → lección validada
  → model bundle sellado → shadow pareado → promote/rollback
```

- `mova_fpl.engine.runner.decide()` es la única autoridad de decisión.
- `mova strategy prepare` reconstruye una memoria estratégica sellada desde planes, decisiones y
  reviews de GWs anteriores y lecciones validadas. No usa historial conversacional ni incorpora
  decisiones de la GW en curso.
- `mova execute` sella riesgo, diff, lease apply-once y verificación. `execute ui-plan` cruza
  pre-state, slots DOM y controles semánticos C/VC después del claim. El wrapper host materializa
  capitanía R2. El instruction stream de XI/banca está implementado y es verificable en modo de
  contrato, pero su entrypoint productivo permanece cerrado hasta los rehearsals; R3 también
  falla cerrado. Los controles efectivos siguen bloqueando escrituras.
- `mova execute rehearsal` importa evidencia browser read-only sellada. Readiness cuenta una sola
  prueba aprobada por GW/capacidad/versión y rechaza fuentes alteradas o intentos de escritura.
- `mova execute rehearsal-capability-probe` deriva evidencia de lineup/R3 exclusivamente desde
  probes DOM allowlisted y conciliados; observar controles nunca habilita entrypoints ni commits.
- `mova postgres drill` ensaya el read-path PostgreSQL y su rollback a SQLite con hashes, artifact,
  idempotencia y métricas, sin cambiar el writer productivo.
- `mova postgres roles` rota y prueba identidades separadas para aplicación y sólo lectura;
  owner queda reservado a migraciones/imports y ningún secreto entra a logs o artifacts.
- Los scripts host de recuperación API/PostgreSQL toman locks, instalan traps, importan evidencia
  allowlisted y son idempotentes; nunca se ejecutan mediante timer ni amplían autoridad FPL.
- `mova improve` registra experimentos, evaluaciones, lecciones y uso/costo. Aceptar una lección
  no modifica el runtime; `mova improve release` es el único camino que puede activar un bundle
  `minutes+points`, después de hashes válidos, shadow multi-GW y gate determinista.
- `mova model` separa `train`, `predict`, `explain` y `evaluate`. El entrenamiento sólo publica
  un bundle candidato inmutable; no cambia el bundle activo y debe atravesar el release gate.
- `mova cost report` muestra consumo y reservas contra límites por job, GW y mes; research y
  deliberación reservan capacidad atómicamente antes de entrar a la cola.
- `mova review auto` atribuye causas después del scorecard final y exige recurrencia multi-GW
  antes de crear una propuesta experimental.
- `mova harness workflow` reconstruye el grafo vigente desde el ledger y separa una terminación
  segura por policy de una falla real de dependencias. El drill hermético comprueba orden,
  fail-closed, deadline e idempotencia sin llamar agentes ni tocar FPL.
- `mova watchdog` refresca primero un probe sanitizado del host y expone cualquier resultado
  fallido de los servicios programados en status, doctor y cockpit. También inspecciona el
  heartbeat y, de forma independiente al importador, la cola
  aislada de agentes. Requests huérfanos, terminales, inválidos, demasiado viejos o ligados a un
  tombstone abren un P1 deduplicado; la API `/api/v1/agent-queue`, `doctor` y las métricas
  `mova_agent_queue_*` exponen el estado sin publicar prompts. También expira permisos no usados
  de forma idempotente y detecta permisos ausentes/alterados/huérfanos o starts sin cierre.
- `mova cockpit` compone funciones, autoridad, workflow, costos, readiness y alertas para humanos
  y agentes. `mova triage` enlaza incidentes con jobs/correlations sin ejecutar reparaciones. El
  dashboard ejecutivo resume ese contrato sin exponer endpoints técnicos ni controles mutables.
- El sentinel deadline-aware sólo abre incidentes cuando faltan hitos dentro de T−6h/T−3h o una
  ejecución entra en estado terminal inseguro; las esperas normales siguen observables sin ruido.
- `HOST_RECOVERY_DRILLS_PROVEN` exige cinco escenarios: API, PostgreSQL, browser, outage
  combinado y reboot real. El wrapper de preparación sella backups, boot ID, revisión, tick,
  controles y team state, pero nunca ejecuta el reboot; un servicio systemd valida la recuperación
  en el boot siguiente y deja el gate pendiente si no existe evidencia importada.
- `mova alerts channel` expone sólo estado, owner y fingerprint del destino. El webhook externo
  permanece opt-in mediante un secreto Docker; sin configuración, journald sigue funcionando y
  readiness declara pendiente el canal externo. El drill prueba payload mínimo, redacción y
  propagación de fallos sin DNS ni llamadas externas.
- `mova alerts test` crea un P3 de prueba en el outbox, reclama exclusivamente ese evento y
  persiste una entrega 2xx ligada al fingerprint vigente. Replay exacto no repite la llamada;
  cambiar identidad con la misma clave falla por conflicto. Configurar el secreto no basta para
  A1: readiness exige también este live-ping.
- El tick no interpreta Markdown: persiste un `DecisionEnvelope` JSON ligado al manifest real.
- Una propuesta sin GW previa asentada, proyección aprobada, team state fresco o ventana válida
  queda `blocked`; solo una que supera todos los hard gates queda `staged`.
- Strategist y Critic consumen el envelope sellado en un worker one-shot sin DB, browser ni
  secretos. Su `Intervention` es solo evidencia `shadow_only`; no modifica el envelope ni el MILP.
- El worker enruta Researcher a `gpt-5.6-luna` con razonamiento `medium` y Strategist/Critic a
  `gpt-5.6-terra` con razonamiento `high`; ambos usan la suscripción Codex, sin fallback a API.
- `mova_fpl` solo hace HTTP `GET`; no escribe en FPL.
- El browser autenticado vive aislado y sus mutaciones están gobernadas por controles.
- Supabase no forma parte del runtime; se usa únicamente para seguimiento PM.
- SQLite sigue siendo el writer del ledger operativo del harness. PostgreSQL es writer del
  data service FPL/odds/WhoScored y conserva un espejo shadow del harness, sincronizado de forma
  idempotente por ciclo/semana; su paridad/frescura son visibles sin entregar secretos a la API.

## Repositorio

```text
mova_fpl/       dominio, datos, modelos, optimizador, engine y control plane
tests/          contratos herméticos e integración explícita con datos
deploy/         imágenes, scripts operativos y unidades systemd
docs/           arquitectura, runbooks, decisiones y specs
decisions/      decisiones de jornada y evidencia textual versionada
models/         manifests ligeros; los joblib viven fuera de Git
.agents/        skills nativas para operar el proyecto
```

Documentos principales:

- [Índice técnico](docs/README.md)
- [Operar una jornada](docs/operations/gameweek.md)
- [Contrato `mova` y diagnóstico](docs/operations/operator.md)
- [Cockpit, triage y dashboard ejecutivo](docs/operations/cockpit.md)
- [Servicio autónomo de datos](docs/operations/data-service.md)
- [Servicio analítico y operaciones del modelo](docs/operations/analytics-service.md)
- [Operar el VPS](docs/operations/vps.md)
- [PostgreSQL shadow](docs/operations/postgres-shadow.md)
- [Plan y research verificable](docs/operations/strategic-research.md)
- [Lifecycle de decisión](docs/operations/decision-lifecycle.md)
- [Arquitectura del motor](docs/architecture/decision-engine.md)
- [Autonomous Harness v1](docs/specs/fpl-autonomous-operator/10-autonomous-harness-v1.md)

El capítulo Mundial 2026, el motor FPL con leakage, visualizaciones y outputs históricos se
retiraron del árbol operativo. Permanecen recuperables en el tag
`archive/pre-harness-cleanup-2026-08-23`; ver [historia del repositorio](docs/history.md).

## Laboratorio analítico 0.7.0

La arquitectura candidata de participación reciente y el planificador de valor
conjunto de chips se describen en el [experimento EXP-021](experiments/season_value/README.md).
Su integración conserva el entrenamiento auditable, hashes y shadow con
liquidación por jornada. La versión del software no implica promoción del
modelo ni habilitación de escrituras FPL.

El [experimento EXP022](experiments/season_value/TRANSITIONS.md) evalúa persistencia
de oportunidades: mejora el pronóstico del mecanismo, pero empata en PVA-38
con `season_value` bajo entradas verificadas. El benchmark v2 registra el resultado
nulo y excluye una corrida invalidada; el motor productivo permanece en v0.7.0.
