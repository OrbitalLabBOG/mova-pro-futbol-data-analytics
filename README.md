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

G108: recuperadas 185 versiones históricas de EPL Fantasy Geek (39,22 MB
con contexto). Se decodificaron 118.634 estados de jugador en 183 versiones;
precios y acumulados conservados sin asignar disponibilidad predeadline. G109
contrasta su contexto de clubes con 2014/15 y 2015/16: 118.549 pares ID/código
coinciden con GT y 85 discrepancias permanecen identificadas. G110 acredita
publicación externa para 94 snapshots (62.398 estados), sin asignar deadlines
ni habilitar entrenamiento.

G107: dos CSV de un taller recuperados: uno tiene estructura inválida; el otro,
567 perfiles acumulados sin ID, jornada ni fecha de captura. Comparación por
nombre preservada como candidata; no se añaden etiquetas al GT.

G106: archivo Footieviz y versiones históricas preservados: 17 capturas,
15 contenidos únicos. Sus 99 filas de 2013/14 coinciden con el archivo existente;
las bases SQLite están vacías. No añade etiquetas ni temporadas.

G105: seis perfiles con totales inconsistentes se contrastaron con sus capturas
vecinas: todas concuerdan antes y después. Se conserva la discrepancia de un
punto, sin corregir etiquetas; reproducción idéntica desde el archivo restaurado.

G104: corte activo restaurado y verificado: 43.741 archivos, 23,56 GB de
contenidos únicos, con GT v8 explícito. Las auditorías recientes se reprodujeron
desde la copia restaurada; no equivale a un backup offsite.

G103: seguimiento de 1.446 snapshots muestra que las tres filas candidatas 0/0
dejan de aparecer cuando los perfiles muestran otro club. Se conservan las trazas
y no se promueven como etiquetas finales faltantes.

G102: 173 de las 177 variantes antes rechazadas se enlazan sin inventar
marcadores. Se detectan 16.928 ceros sin marcador que corresponden a minutos
positivos en el GT final; quedan excluidos como etiquetas de no participación.

G101: de 253 variantes de historial, 62 se reconcilian con fixtures y totales.
La comparación con GT v8 conserva 599 discrepancias de estado y dos claves
candidatas ausentes (ambas 0/0); no se incorporan automáticamente al GT.

G100: colección cruda de 2.579 snapshots adquirida (17,06 GB), con hashes
verificados. Auditoría distingue 2.572 estructuras válidas, dos vacíos y cinco
JSON inválidos; no implica nuevas etiquetas ni disponibilidad predeadline.

G99: GT experimental v8 incorpora las identidades verificadas de los 24 jugadores
pendientes de 2014/15 (421 filas). Las 24.876 filas de esa temporada quedan
enlazadas, conservando todas las etiquetas. Paquete reproducido; producción intacta.

G97: la auditoría de procedencia encuentra pronósticos, pero ningún resultado en
12 campos observados de los 408 registros incompletos de GW38 2013/14. No se
imputan ceros ni aumenta la cobertura; ver el [registro de datos](experiments/data_ground_truth/README.md).

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

La capa experimental conserva los datos crudos fuera de Git, con manifiestos,
SHA-256, fuentes fijadas por commit y auditorías reproducibles. El
[registro de gates G1–G110](experiments/data_ground_truth/README.md) contiene
adquisiciones, conciliaciones, cuarentenas y comandos. El estado vigente es:

| Capa | Cobertura verificada | Límite pendiente |
| --- | --- | --- |
| Etiquetas FPL, GT experimental v8 | 303.126 filas de jugadores, doce temporadas 2014/15–2025/26; 322 filas de managers separadas | Son resultados retrospectivos, no entradas disponibles antes del deadline |
| Bootstrap raw | 7.837 snapshots; estados, precios, clubes y posiciones | Disponibilidad y semántica varían por campo y temporada |
| Estados con publicación histórica acreditada | 196/199 deadlines; 38/38 en cada temporada 2021/22–2025/26 | GW1–3 de 2026/27 sin testigo; selección desconocida no se convierte en elegibilidad |
| Calendarios con publicación histórica acreditada, G35 | 193/199 deadlines; 38/38 en 2023/24, 2024/25 y 2025/26 | Seis ventanas pendientes y frescura desigual: 93 calendarios tienen commit de hasta 48 horas; en 2025/26 son 14/38 |
| Índice común de calendarios, G37 | 195/199 deadlines: 193 con publicación externa y dos con ledger propio | Cuatro ventanas pendientes; los tipos de reloj y evidencia se conservan separados |
| Rendimiento raw, G31 | 143.720 filas y 22 campos tipados; sin valores numéricos inválidos | 31.071 descensos de celda, 27.211 entre GW1–2: falta resolver período y semántica antes de calcular deltas |
| Período de estadísticas GW2, G43 | 3.091 jugadores, cinco temporadas y 40.183 celdas coinciden con GW1 final | 37 jugadores históricos sin referencia; 2026/27 sin etiquetas en el paquete; diagnóstico retrospectivo, sin admisión a entrenamiento |
| Acumulados por jornada y fecha, G44 | 191 ventanas, 138.830 estados; 138.544 iguales, tres diferentes y 283 sin referencia | Nueve celdas de diferencia compatibles con la corrección histórica de Ferguson; no se modifica el snapshot |
| Historia de la discrepancia, G45 | 219 capturas de Ferguson: pérdida observada de tres componentes en febrero y recuperación en marzo de 2025 | Ventanas nominales entre archivos; no acreditan el instante ni la causa de una corrección de la API |
| Componentes por partido, G46 | xG/xA y starts: 113.260 filas en cuatro temporadas; métricas defensivas antiguas y 2025/26 preservadas | Valores retrospectivos; definiciones entre épocas y disponibilidad histórica pendientes de conciliación |
| Conciliación suplementaria, G47 | 110.018 estados; igualdad exacta en campos comparables de 2023/24 y 2025/26 | 2022/23 tiene ausencia y cambios de precisión; 2024/25 conserva nueve diferencias de Ferguson; sin admisión automática |
| Introducción de campos 2022/23, G48 | 1.458 capturas: ausencia, once capturas con ceros y cambios posteriores de precisión | Fechas nominales del archivo; ceros observados no se sustituyen con datos posteriores |
| Filtro observable por campo, G49 | 143.720 estados y 199 ventanas; 2.423.700 celdas pasan el filtro preliminar | No usa igualdad con GT para decidir inclusión; requiere contratos semánticos antes de entrenamiento |
| Inventario raw consolidado, G50 | 21 conjuntos con manifiesto, 24.462 contenidos únicos verificados; 141 archivos de otros formatos inventariados | Incluye versiones históricas; seis auxiliares SQLite clasificados en G51; cobertura temporal aún pendiente |
| Auxiliares Differential, G51 | Tres WAL vacíos y tres SHM vinculados a bases ya archivadas; lectura autónoma idéntica | No son nuevas fuentes; se preservan y no se atribuye el proceso que los creó |
| Cobertura conjunta, G52 | Estado publicado + calendario: 38/38 en 2023/24–2025/26; 37/38 pasan campos básicos y xG/starts | GW1, elegibilidad y reglas/chips aún impiden declarar replay completo; la búsqueda antigua no añadió temporadas |
| Selección observada, G53 | 48.738 estados con can_select explícito; 94.982 ausentes; 6.081 seleccionables con status distinto de a | Solo 2025/26 tiene flags en toda la temporada cerrada seleccionada; no inferir permisos de status o can_transact |
| Consistencia de chips, G54 | 38 bases coherentes; 14 declaraciones futuras Free Hit con tamaño 16 frente a cuotas que suman 15 | Contradicción conservada; no afecta declaraciones dentro de ventana; reglas dependientes de historia requieren contrato |
| Paquete portable, G55 | 21 corpus públicos, GT y contexto documental; 27.399 rutas con objetos deduplicados y restauración verificable | Paquete interno local; no es respaldo externo, publicación ni entorno completo de todos los experimentos |
| Referencia publicada, G56 | 152 agregados jornada–cohorte y cinco resúmenes de 2018/19, extraídos y reconciliados | Cohortes por rank final; referencia descriptiva, sin acciones individuales ni admisión como benchmark causal |
| Etiquetas antiguas, G57 | 114 ventanas auditadas en 2011/12–2013/14; 732 apariciones con puntos desconocidos | Cobertura sobre filas archivadas, no población completa; NULL no se convierte en cero |
| Período suplementario GW1, G58 | 3.622 estados; 9.562/9.625 celdas comparables de starts/xG coinciden con temporada anterior | 63 diferencias conservadas; métricas defensivas GW1 2025/26 sin referencia previa por partido |
| Referencia defensiva anual, G59 | 894 observaciones, 562 jugadores de 2024/25; 392 contribuciones positivas; GW1 siguiente coincide en 508/511 códigos comparables | Tres componentes publicados sólo como ceros; no reconstruyen partidos ni nuevos puntos FPL |
| Defensa por partido, Core G60 | 11.567 filas enlazadas, 380 partidos; cubre todas las apariciones positivas del GT 2024/25 | Seis campos de proveedor separados; 2.942 diferencias de minutos; equivalencia FPL pendiente |
| Composición defensiva anual, G61 | CBIT/CBIRT con tackles coincide en 368/369 códigos comparables; tackles_won sólo en 30/369 | Una diferencia de una acción; concordancia anual no demuestra igualdad por partido |
| Contraste defensivo por partido, G62 | 12.754 filas EPL 2025/26, cobertura de 11.492 apariciones positivas; métricas separadas por rol/minutos | En campo con minutos: contribución derivada 9.841 iguales, 616 distintas, 268 desconocidas; no fusionar con FPL |
| Procedencia defensiva, G63 | 108 versiones descargadas; 12.461 valores nativos conservan el relleno histórico; FPL internamente consistente | Core documenta reparto proporcional en dobles jornadas; su columna nativa no es GT independiente por partido; 293 huecos sin recuperación |
| Detalle de partidos, G64 | 304 CSV nuevos: 97.007 filas en ocho tablas, las ocho cubren 380 partidos | Faltan apariciones individuales; cobertura no prueba exactitud ni disponibilidad predeadline |
| Integridad de titulares, G65 | 378/380 conjuntos de titulares concuerdan con FPL; 301 referencias de jugador adicionales resueltas | Dos partidos con cinco titulares extra y cinco faltantes cada uno; sin reparación histórica ni admisión predeadline |
| Huecos y exclusiones, G66 | 86 archivos contrastados; 75 claves ausentes persisten; 48 incidentes descartados conservados | Sin recuperación por ID exacto en los cortes examinados; exclusiones del proveedor no se convierten en ceros |
| StatsBomb, G67 | Corpus separado de investigación: 380 partidos 2015/16 y 38 de 2003/04 | Licencia restrictiva: sin admisión comercial/runtime, redistribución raw ni enlace FPL todavía; ver atribución y métricas en el registro de gates |
| Enlace de partidos, G68 | 380/380 partidos StatsBomb 2015/16 enlazados; 24.741 filas FPL cubiertas | Clubes y fecha concordantes; marcador no verificable en PL, identidad de jugadores pendiente; sólo investigación |
| Identidad StatsBomb, G69 | 462 jugadores enlazados; 9.645/10.469 apariciones positivas FPL cubiertas | 824 apariciones sin identidad resuelta; dos testigos de club/partido y nombres, sin admisión comercial o productiva |
| Alias declarados, G70 | 490 jugadores; 10.220/10.469 apariciones positivas cubiertas (+575) | 249 pendientes; alias explícito completo y dos partidos únicos; sin pérdida de enlaces G69, uso sólo investigativo |
| Nombres completos FPL, G71 | 493 identidades; 10.286/10.469 apariciones positivas cubiertas (+66) | 183 pendientes; nombres respaldados por ficha del mismo código oficial; sólo investigación |
| Goles por eventos, G72 | Marcador interno concordante en 760 lados; comparación FPL de 12.939 filas enlazadas | Difieren 12/876 casos no cero de gol y 7/37 de autogol; conservar fuentes, sin reparación de GT |
| Coherencia de puntos FPL, G73 | 24.741/24.741 filas de 2015/16 cuadran con fórmula histórica declarada | Las 19 discrepancias de atribución conservan coherencia FPL; sustituir goles aisladamente la rompe, sin reparación automática |
| Códigos PL ausentes, G74 | 496 identidades y 10.312/10.469 apariciones positivas enlazadas; +26 | 157 pendientes; nombre FPL único y aparición del mismo partido, sin relajar dos testigos ni modificar raw |
| Variantes documentadas, G75 | 499 identidades y 10.361/10.469 apariciones positivas enlazadas (98,97%); +49 | 108 pendientes; tres equivalencias revisadas con fuente/hash, sin inferencia general de apodos |
| Grafía y registro FIFA, G76 | 501 identidades; 10.397/10.469 apariciones positivas (99,31%); +36 | 72 pendientes; aparece una discrepancia adicional de autogol, conservada sin reparar GT |
| Apariciones de temporada, G77 | 503 identidades; 10.422/10.469 apariciones positivas (99,55%); +25 | 47 jugadores de una aparición pendientes; cubiertos 503/503 con al menos dos, sólo identidad retrospectiva |
| Archivo consolidado, G78 | G55 más 39 directorios y 27 archivos explícitos; 30.295 rutas, 27.449 contenidos únicos (3.189.886.957 bytes) | Corte interno con grupo StatsBomb separado; no añade etiquetas ni acredita respaldo externo |
| Libros históricos, G79 | Tres XLSM, nueve hojas y 2.266 filas de precios/métricas agregadas preservadas | Sin código oficial, fixture ni GW; nombres de archivo no acreditan período; cero nuevas temporadas completas |
| Búsqueda hasta deadline, G80 | Veinte horas adicionales de GHArchive verificadas para GW32 2021/22 y GW23 2022/23 | Sin testigos nuevos; calendario sigue en 195/199; resultado negativo acotado al repositorio y horas consultadas |
| Antigüedad de calendarios, G81 | Tres ventanas pendientes tienen calendarios anteriores publicados, de 14,65–20,97 días; diagnóstico de cambios por club/GW | 9, 35 y 23 campos difieren de referencias posteriores; selección sigue 195/199 y no se admiten referencias futuras como entradas |
| Anuncios de reprogramación, G82 | Cinco páginas oficiales archivadas; 47 horarios, ocho condicionales; 20 cambios de kickoff coinciden con declaraciones actuales | Cuatro horarios difieren de ambos snapshots; fecha visible no prueba contenido histórico; sin elevar 195/199 ni admisión temporal |
| Integridad de temporadas parciales, G83 | 29.927 etiquetas antiguas pasan controles estructurales; 16.724 localías derivadas por clubes conservando NULL crudo | 3.465 filas con etiquetas incompletas; no implica cobertura poblacional ni admisión de entrenamiento |
| Archivo Azure, G84 | 2.524 snapshots / 3,12 GB adquiridos y reproducidos; cobertura nominal 37/38 GW en 2020/21 y 38/38 en 2021/22 | 1.620.223 observaciones de estado; relojes y publicación separados; sin nuevas etiquetas jugador–partido ni admisión temporal |
| Enlace Azure–GT, G85 | 52.639/52.640 observaciones jugador–ventana enlazan por ID estacional y código oficial; un conflicto en cuarentena | 35 apariciones positivas sin identidad en alguna captura; no se imputa ausencia ni se admite replay temporal |
| Observación de jugadores, G86 | 309 identidades trazadas en 2.524 snapshots; 35 huecos positivos distinguidos en 29 ausencias posteriores, cuatro intervalos y dos cambios de variante | Primeras observaciones nominales, no fechas de alta; sin imputación, alias automático o admisión temporal |
| Archivo portable vigente, G104 | 43.741 rutas y 40.850 contenidos únicos (23,56 GB); GT activo v8, paquete parcial G94 y evidencia hasta G103, con reproducciones desde la restauración | Corte interno; G92 conservado, sin acreditar backup externo o admisión temporal |
| Collector propio, G36 | 55 bundles públicos; 34.512 estados de jugadores y 20.900 observaciones de fixtures | Dos candidatos anteriores a GW2/GW3 2026/27 vinculados al cierre de ingesta; evidencia interna identificada en el índice común G37 |
| Reglas y chips de snapshots | Explícitos desde GW16 de 2024/25 y en toda 2025/26 | Faltan reglas históricas anteriores e interpretación de overrides |
| Reglas documentales oficiales, G38 | 10 artículos archivados, 30 afirmaciones parciales en seis temporadas | Descargas actuales: la fecha del artículo no prueba disponibilidad histórica; no son un intérprete de reglas |
| Calendarios PDF oficiales, G39 | 380 cruces de 2013/14 y 760 celdas FDR de 2025/26 | Versiones aisladas; sin disponibilidad histórica acreditada ni nuevas etiquetas FPL |
| Conciliación FPL Discovery 2014/15, G40 | 24.876 filas; 665 códigos coinciden con GT v5 y 46 son candidatos | Cero filas nuevas; los candidatos cubren 674 filas sin minutos jugados y siguen sin admisión al GT |
| Enriquecimiento de identidad, G41 | GT v6 enlaza 19 jugadores y 223 filas de 2014/15 mediante código y nombre completo | Quedan 27 jugadores y 451 filas con identidad limitada a la temporada; sin cambios deportivos |
| Extensión de perfiles, G42 | GT v7 enlaza otros tres jugadores y 30 filas de 2014/15 | En ese corte quedaron 24 jugadores y 421 filas pendientes, resueltos en G99; no añade resultados ni acredita disponibilidad histórica |
| Fuentes antiguas complementarias | Material parcial desde 2010/11 y totales desde 2006/07 | No cuentan como nuevas temporadas completas; persisten huecos de población e identidad |

G30 combina calendarios completos de dos fuentes, revalidando cada testigo contra
su evento público y grafo Git. No mezcla filas de capturas distintas. En 2025/26
la antigüedad nominal máxima es 344,67 horas; la hora del commit no es la hora de
captura API. [Resultados G30](experiments/data_ground_truth/results-g30.json).

Los datos permiten investigar más temporadas y estados, pero todavía no acreditan
un replay causal completo ni mejoras del modelo. GT v8, evidencia temporal y
reglas se versionan por separado; este trabajo no habilita entrenamiento ni
modifica el histórico productivo de 253.890 filas. El siguiente trabajo de datos
es cerrar ventanas de publicación, mejorar frescura y conciliar el período de
las estadísticas raw, especialmente en GW1. La validación numérica G31 no
acredita acumulados de la temporada corriente ni deltas por jornada.
[Resultados G31](experiments/data_ground_truth/results-g31.json).
G32 contrasta 3.622 filas previas a GW1: 2.739 coinciden con los componentes de la
temporada anterior, 19 difieren y 864 carecen de código en la referencia. Esto
respalda la hipótesis de estadísticas previas, pero no autoriza reasignación global de período
ni rellenar snapshots con totales finales.
[Resultados G32](experiments/data_ground_truth/results-g32.json).
G33 rastrea las diecinueve excepciones en 694 snapshots de pretemporada: ocho
altas observadas y once estados constantes, sin una captura anterior que resuelva
la discrepancia. Se conservan como excepciones, sin imputación desde el GT final.
[Resultados G33](experiments/data_ground_truth/results-g33.json).
G34 añade siete ventanas con calendarios anteriores acreditados y conserva 24
diferencias futuras de horario como diagnóstico. La selección alcanza 191/199;
no aumenta frescura ni incorpora valores posteriores.
[Resultados G34](experiments/data_ground_truth/results-g34.json).
G35 acredita GW1 y GW5 de 2024/25 mediante nuevas horas de GH Archive y búsqueda
por commits descendientes. La selección deduplicada alcanza 193/199 deadlines,
con seis pendientes. Las nuevas pruebas acreditan publicación, no captura API.
[Resultados G35](experiments/data_ground_truth/results-g35.json).
G36 recupera bootstrap/fixtures del collector propio, verifica 55 manifiestos y
los vincula al ledger readonly. Usa el cierre de ingesta como disponibilidad,
pues `observed_at` se asigna antes de descargar. Entrega dos candidatos 2026/27
con origen interno explícito, incorporados al índice común G37.
[Resultados G36](experiments/data_ground_truth/results-g36.json).
G37 reproduce las auditorías G35 y G36 antes de combinar sus índices. Alcanza
195/199 deadlines; faltan 2021/22 GW31–32, 2022/23 GW23 y 2026/27 GW1.
Conserva edad de commit y edad de inicio de captura como métricas distintas,
sin afirmar replay completo ni admisión a entrenamiento.
[Resultados G37](experiments/data_ground_truth/results-g37.json).
G38 incorpora artículos oficiales sobre cambios de chips, límites de transferencias
y excepciones de temporada. Conserva los HTML, hashes, fecha declarada y localizadores
de cada afirmación. La evidencia es retrospectiva y no se hereda entre temporadas.
[Resultados G38](experiments/data_ground_truth/results-g38.json).
G39 valida dos PDFs oficiales y extrae la dificultad mediante la leyenda de colores
del documento. Los 380 cruces FDR coinciden con el archivo FPL 2025/26; se conservan
10 diferencias de jornada y 304 de dificultad frente a la versión final como
diagnóstico retrospectivo. [Resultados G39](experiments/data_ground_truth/results-g39.json).
G40 contrasta otro CSV de 2014/15 con el histórico reconciliado: no hay diferencias
de valores ni filas nuevas. La base original tenía 225 identidades pendientes;
el contraste con GT v5 reduce los pendientes reales a 46 candidatos, todos sin minutos jugados.
[Resultados G40](experiments/data_ground_truth/results-g40.json).
G41 contrasta perfiles completos posteriores y deriva GT v6 sin cambiar resultados,
particiones temporales ni archivos de otras temporadas. Su versión vigente está
en [current-labels.json](experiments/data_ground_truth/current-labels.json).
[Resultados G41](experiments/data_ground_truth/results-g41.json).
G42 audita 620 perfiles del dump histórico 2015/16 y deriva GT v7 mediante
código y nombre completo coincidentes. Conserva los paquetes padres y reproduce
los quince archivos en una raíz independiente.
[Resultados G42](experiments/data_ground_truth/results-g42.json).

G88 añade archivos parciales de 2013/14 (17.805 filas, 291/380 partidos) y
2014/15 (1.756 filas, GW1–3), más 19 versiones históricas del segundo archivo.
Las filas de 2014/15 coinciden con GT v7 en minutos, puntos y jornada; persisten
tres diferencias de código de jugador. G89 contrasta 2013/14 con Differential: 7.998 apariciones comunes sin
diferencias en valores conocidos, 9.807 ceros explícitos adicionales y 52 puntos
faltantes recuperables como candidatos; quedan nueve apariciones con puntos
desconocidos sin resolver. No aumenta todavía el número
de temporadas del GT. [Resultados G88](experiments/data_ground_truth/results-g88.json).

G90 preserva otras 44 versiones de estados 2014/15, de las cuales 30 tienen
contenido nuevo frente a G88. El último archivo cubre GW1–6 y sus 3.596 filas
coinciden con GT v7 en minutos, puntos y jornada; seis diferencias de código
permanecen pendientes. Siete versiones no concilian por filas sin marcador.
[Resultados G90](experiments/data_ground_truth/results-g90.json).

G91 explica la discrepancia de código de Isaiah Brown: 65 registros de
procedencia, 50 contenidos distintos, usan `81132`; perfiles posteriores
corroboran `112516`. La correspondencia candidata queda limitada al SHA del
archivo y al ID de origen, sin sustitución global ni cambios del GT.
[Resultados G91](experiments/data_ground_truth/results-g91.json).

G93 contrasta los nueve puntos desconocidos de GW34 2013/14 con referencias
anuales: siete tienen residuo condicional cero y dos carecen de referencia en
la fuente examinada. Los nueve siguen sin etiqueta observada; las inferencias
se conservan separadas. [Resultados G93](experiments/data_ground_truth/results-g93.json).

G94 consolida el histórico parcial 2013/14 en un paquete independiente:
20.248 etiquetas observadas, 417 filas desconocidas e inferencias anuales
separadas. [current-partial-labels.json](experiments/data_ground_truth/current-partial-labels.json)
fija su versión; no sustituye el GT v8 de doce temporadas.
[Resultados G94](experiments/data_ground_truth/results-g94.json).

G95 mide el cambio de cobertura en 2013/14: GW1–30 incluye positivos y ceros;
GW31–38 sólo apariciones positivas conocidas. Los 408 minutos desconocidos están
en GW38. La proporción observada no es una probabilidad de jugar y el paquete
sigue sin admisión para entrenar participación.
[Resultados G95](experiments/data_ground_truth/results-g95.json).

G96 preserva 723 perfiles alternativos de 2015/16 y verifica su solapamiento:
los historiales por partido coinciden con la fuente existente. Añaden resúmenes
anuales y diferencias de estado, sin nuevas etiquetas por partido.
[Resultados G96](experiments/data_ground_truth/results-g96.json).

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
