---
type: research
name: MOVA historical raw data and ground truth audit
updated: 2026-09-05
status: experimental
---

# Histórico crudo y ground truth: raw-history-v1

Corte del 5 de septiembre de 2026 (Colombia). Este experimento adquiere y audita
histórico público sin escribir en el canónico, entrenar modelos ni modificar el VPS.
Los resultados medidos están en [results.json](results.json); los bytes y tablas
intermedias permanecen fuera de Git. No es una publicación de un dataset.

## Reproducción

Usar el entorno Python 3.13 del proyecto. `RAW_HISTORY_ROOT` debe apuntar a un
directorio de artefactos externo al repo; `CANONICAL_DB` al histórico existente.

```bash
python -m experiments.data_ground_truth.raw \
  --root "$RAW_HISTORY_ROOT" --pins experiments/data_ground_truth/pins.json
python -m experiments.data_ground_truth.audit \
  --root "$RAW_HISTORY_ROOT" --db "$CANONICAL_DB" \
  --out "$RAW_HISTORY_ROOT/audit.json"
python -m experiments.data_ground_truth.complement \
  --root "$RAW_HISTORY_ROOT" --db "$CANONICAL_DB"
pytest -q
```

`pins.json` fija commits completos. La selección evita contar varias veces las
copias por torneo de una misma jornada. `inventories/` conserva el árbol completo
para conocer también lo no descargado. `manifest.json` registra URL, commit,
SHA-256, tamaño y fecha de descarga; `objects/` publica bytes completos de forma
atómica. Repetir la adquisición comprueba hashes y reutiliza objetos. Un fallo
se registra y devuelve exit 2; corrupción nunca se acepta como cache válida.

`audit.json` mide por temporada/campo tanto todas las filas como aquellas con
minutos > 0; valida claves, rango de minutos, fechas e identidad. Conserva errores
de parseo como incidencias, sin sustituir caracteres ni inventar ceros. Su exit 0
significa que terminó la medición, no que todos los datos fueron aprobados.
`complement.json` contrasta las fuentes y registra hashes de las tablas derivadas.
Conflictos de contenido para la misma clave se excluyen de staging; los originales
siempre permanecen en raw. Dobles jornadas se agregan solo para comparar jugador–GW.

## Resultado medido

- Canónico: 253.890 filas, diez temporadas, 380 fixtures por temporada, sin claves
  repetidas/nulas, minutos fuera de 0–90 ni kickoff inválido. Ocho temporadas tienen
  además contraste por ID con `fixtures.csv`: ningún partido finalizado faltante.
  No hay ese archivo en la selección disponible de las primeras dos temporadas.
- La GW7 ausente en 2022/23 no implica pérdida de partidos: están los 380 IDs.
  En 2019/20 el origen usa jornadas 39–47 tras la interrupción; no recortar a 38.
- 427 archivos descargados, 72.529.667 bytes, cero errores de adquisición.
  Tres `merged_gw.csv` antiguos (2016–19) no son UTF-8 y quedan pendientes de un
  contrato de decodificación explícito. Esto no altera las filas canónicas existentes.
- `players_raw.csv` enlaza por `(season, element)` el 100% de las filas con `code`:
  cero IDs o códigos oficiales duplicados dentro de temporada. Exportamos diez
  tablas `staging/<season>/player_identity.csv`, con código oficial y posición.
  Permiten recuperar posición en 90.496 filas de 2016/17–2019/20 para investigación.
- El nombre normalizado NO es identificador único: aparecen colisiones Danny Ward,
  Ben Davies y Álvaro Fernández. Migrar el consumidor a código oficial requiere una
  versión nueva de features/modelos y evaluación; este experimento no cambia esa API.
- Los códigos oficiales de las dos fuentes coinciden para los 804 jugadores de
  2024/25 y los 841 de 2025/26, sin discrepancias ni IDs sin resolver.
- FPL Core 2024/25: 380 partidos y 11.567 observaciones jugador–partido.
- FPL Core 2025/26: 525 registros de partidos, 521 marcados finalizados; 380 Premier,
  64 Champions, 28 Europa, 13 Conference, 40 EFL Cup. Son 145 registros adicionales
  fuera de Premier, no una garantía de cobertura completa de copas. No aparece FA
  Cup en el inventario de esa temporada pese al alcance descrito en el README origen.
- Sus 15.340 observaciones jugador–partido enlazan a elementos canónicos; 749 carecen
  de kickoff válido y no permiten calcular descanso. Las 29.338 parejas jugador–GW
  comparables coinciden exactamente en puntos/minutos. Ambas fuentes parten de FPL:
  concordancia no equivale a validación independiente de cada resultado.
- 2026/27 se archiva separado: 473 partidos programados, solo 37 marcados finalizados
  y 1.055 observaciones de jugador. No cuenta como temporada cerrada del benchmark.

## Brecha que permanece y criterios de promoción

**Ground truth retrospectivo y estado conocido antes del deadline son contratos
separados.** Todos los objetos de esta importación tienen `available_at=null` y
`eligible_predeadline=false`. Fecha de partido, deadline descrito por el proveedor,
commit y descarga actual no prueban cuándo estuvo disponible una observación.
Las tablas staging conservan esa prohibición; todavía no las consume `Store`.
Una posición al cierre puede servir como etiqueta de temporada; un club al cierre
no debe trasladarse hacia atrás a jornadas anteriores a un fichaje.

Orden de trabajo respaldado por esta auditoría:

1. Resolver identidad con código oficial; verificar posición y contratos de
   decodificación, sin joins difusos por nombre. Versionar el canónico candidato
   por separado y comparar con este SHA antes de sustituir cualquier dataset.
2. Completar kickoff, clubes y estado final de las copas; buscar FA Cup y amistosos
   mediante fuente verificable. No convertir los 145 registros en un denominador
   supuesto de cobertura total. Medir partidos esperados/observados por competición.
3. Reconstruir snapshots históricos de calendario, bajas, precios y ownership con
   evidencia de publicación anterior al deadline; si no existe, conservar desconocido.
   La captura live actual debe seguir acumulando observaciones fechadas.
4. Sellar folds de entrenamiento/evaluación junto con versión de datos, reglas y
   metadatos de procedencia. No llenar xG ausente antes de 2022/23 con cero ni tratar
   contribución defensiva como puntaje oficial antes de existir esa regla.

Métricas de progreso: partidos finalizados faltantes por ID; cobertura no nula por
campo y entre jugadores que jugaron; identidad resuelta/ambigua; conflictos de
fuentes; pares reconciliados; porcentaje con kickoff válido y porcentaje con
publicación predeadline demostrada. La cantidad de filas sola no es criterio de promoción.
La métrica predeadline verificada de este lote es **0%**, intencionalmente explícita.

## Fuentes y alternativas investigadas

- [Vaastav](https://github.com/vaastav/Fantasy-Premier-League): histórico FPL y
  metadatos oficiales. El archivo LICENSE y README se guardan con el pin.
- [FPL Core Insights](https://github.com/olbauday/FPL-Core-Insights): detalle de
  partidos y snapshots desde 2024/25. README archivado con su declaración de uso;
  no se encontró LICENSE separado en el árbol inspeccionado. La semántica temporal
  del README mezcla cierre de GW y deadline: no constituye prueba temporal por fila.
- [StatsBomb Open Data](https://github.com/hudl/open-data): su
  [inventario](https://raw.githubusercontent.com/hudl/open-data/master/data/competitions.json)
  lista Premier 2015/16 y 2003/04, fuera de nuestras diez temporadas. Puede apoyar
  investigación de eventos, pero no cierra directamente esta brecha histórica FPL.
- Football-data.co.uk: candidato para contraste de resultados/cuotas por partido;
  las páginas oficiales devolvieron error al consultarlas en esta iteración. No se
  contabiliza nueva cobertura ni se trata una cuota de cierre como previa al deadline.

No se reclama una búsqueda exhaustiva de proveedores ni una cobertura total de
lesiones, cuotas o copas. La siguiente promoción depende de resolver esos contratos,
no de descargar más copias del mismo resultado.

## Gate G2: identidad y expansión verificadas

Corte posterior del 5 de septiembre de 2026 Colombia. Resultado independiente en
[results-g2.json](results-g2.json); G1 conserva `results.json` sin reescribirlo.

- `pins-g2.json` amplía a cuatro repositorios: 1.161 archivos, 277.072.011 bytes,
  cero fallos de adquisición. El nuevo root es `raw-history-v2`.
- `decoding.py` admite Latin-1 únicamente para tres SHA-256 revisados. Esos bytes
  no contienen el rango 0x80–0x9f: Latin-1 y Windows-1252 coinciden. No hay fallback
  genérico ni reemplazos Unicode. El auditor detectó un CSV de la fuente adicional
  con caracteres de sustitución ya incorporados; queda en cuarentena.
- `labels.py` exportó 253.890 observaciones en diez CSV de etiquetas con código
  oficial y tipo de posición: cero identidades sin resolver y cero discrepancias
  en claves, puntos o minutos frente al canónico. Recupera la posición de las
  90.496 filas antiguas mediante metadatos de temporada. Son etiquetas retrospectivas;
  no un feed de features disponible antes del deadline.
- El archivo deportivo adicional contiene 17 temporadas 2009/10–2025/26, cada una
  con 380 IDs de fixtures distintos: 6.460 partidos y 241.241 filas jugador–partido
  al excluir las copias agregadas. Añade siete temporadas deportivas anteriores
  a nuestro histórico FPL, sin inventar puntaje Fantasy para ellas.
- El archivo tiene 15 filas con minutos fuera de 0–90 en 2022/23. Sus `playerId`
  son otro namespace que `pl_code`; los IDs de partido de las tablas de jugadores
  tienen cero coincidencias con los IDs de las tablas de eventos. No se adopta la
  unión directa sugerida por el README del proveedor. Todo ese detalle permanece
  en cuarentena hasta reconciliar fixtures e identidad de forma verificable.
- TopMarx aporta resúmenes y deadlines históricos de 2025/26. Que un archivo tenga
  deadline no demuestra su publicación previa; `eligible_predeadline` sigue falso.

```bash
python -m experiments.data_ground_truth.raw \
  --root "$RAW_HISTORY_ROOT" --pins experiments/data_ground_truth/pins-g2.json
python -m experiments.data_ground_truth.labels \
  --root "$RAW_HISTORY_ROOT" --canonical "$CANONICAL_DB"
python -m experiments.data_ground_truth.archive_audit --root "$RAW_HISTORY_ROOT"
```

El subgate de etiquetas con identidad está verificado. El subgate de integración
multifuente sigue abierto: resolver namespaces, minutos anómalos y disponibilidad
temporal. La promoción de un nuevo modelo no forma parte de este gate.

Fuentes nuevas: [Premier League Stats](https://github.com/imadeddine-belkat/Premier-League-Stats)
y [TopMarx FPL mirror](https://github.com/TopMarxFPL/fpl-mirror). Sus README se archivan
con los mismos commits que los datos. El README del primero afirma que las claves
son intercambiables; los resultados de la auditoría contradicen esa afirmación.

## Gate G3: una temporada Fantasy adicional, 2014/15

[results-g3.json](results-g3.json) registra 24.876 observaciones, 711 jugadores,
38 jornadas y 380 fixtures reconciliados, sin diferencias entre la suma de puntos
por partido y el puntaje final de cada jugador. Se conservan 345 observaciones
adicionales de dobles jornadas; la clave es jugador–partido, nunca jugador–GW.
El conjunto de resultados FPL pasa a once temporadas y 278.766 observaciones:
2014/15 más 2016/17–2025/26. La temporada 2015/16 sigue siendo un hueco.

Fuente primaria: [durtal/fantasysocceR](https://github.com/durtal/fantasysocceR),
commit fijado en `pins-g3.json`; 22 archivos / 347.337 bytes archivados. Se leen
solo los objetos R `season201415` y `players201415`, nunca código del repositorio
ni otros objetos del contenedor. La dependencia de conversión es opcional y se
instala en entorno aislado, sin modificar el runtime FPL.

```bash
python -m experiments.data_ground_truth.raw \
  --root "$FPL_2014_ROOT" --pins experiments/data_ground_truth/pins-g3.json
uv run --no-project --with pyreadr==0.5.6 --with pandas==2.3.3 \
  python -m experiments.data_ground_truth.historical_2014 \
  --root "$FPL_2014_ROOT" --archive-root "$RAW_HISTORY_ROOT"
```

La unión de partidos exige coincidencia única de fecha/hora local, oponente y
localía contra el archivo PL 2014/15. El club en cada partido se reconstruye desde
ese fixture; no se copia el club de fin de temporada hacia atrás. La zona horaria
no se inventa y la fecha de publicación sigue desconocida. Se preservan nombres
`final_season_*` para los snapshots de puntos, precio, ownership y club finales,
que NO son insumos disponibles en jornadas previas. El resultado se exporta como
`labels-2014-15.csv`, con SHA-256 y namespaces explícitos.

El gate de resultados por temporada está verificado. Para entrenamiento conjunto
queda pendiente la unión de identidad 2014/15 a código oficial. Tampoco se afirma
que estén reconstruidas las reglas, precios predeadline o acciones legales del
replay 2014/15. Los archivos `pastseasons*.RData` contienen resúmenes por temporada
con sesgo de supervivencia de los jugadores presentes en el snapshot; se archivan
pero no se cuentan como temporadas completas adicionales.

## Gate G4: namespaces de partidos e identidad histórica

Resultado en [results-g4.json](results-g4.json). La unión entre archivos PL exige
una pareja local–visitante única y completa dentro de cada temporada, con ambos
participantes presentes en los registros de jugadores. No se presume igualdad de
IDs ni de jornadas: las rondas cambian en partidos aplazados. El crosswalk enlaza
los 6.460 partidos de las 17 temporadas, conservando ambos IDs y la fecha local.
Un club par duplicado, lado ausente o partido sin correspondencia aborta el build.
Este contrato solo aplica a liga con un partido por pareja local–visitante/temporada.

Las 241.241 observaciones quedan enlazadas: 2.010 sin código oficial y 15 con minutos
fuera de 0–90 permanecen señaladas. Hay 179.439 filas con identidad y minutos
observados dentro de rango, utilizables como etiquetas deportivas bajo esa semántica.
Las restantes con minutos ausentes NO se convierten en no-apariciones. No se sustituye
el valor de minutos FPL por el de PL: son observaciones de fuentes distintas.

En 2014/15 se resolvieron 486 identidades y 17.769 filas: 10.206/10.428 apariciones
con minutos (97,87%). El enlace requiere tokens exactos de nombre normalizado,
coincidencia de club y fixture en dos apariciones distintas, un único código candidato
y ninguna asignación del mismo código a dos IDs FPL. No se escoge el candidato de
mayor score ni se fuerza equivalencia entre posiciones deportivas y posiciones FPL.
Se conservan 225 jugadores sin resolver (incluidos jugadores sin apariciones);
`identity/unresolved.csv` mantiene el detalle. Entre los testigos aceptados hay 3.553
diferencias de minutos: la identidad no se usa para sobrescribir esa discrepancia.

```bash
python -m experiments.data_ground_truth.crosswalk --root "$RAW_HISTORY_ROOT"
python -m experiments.data_ground_truth.identity_2014 \
  --root "$FPL_2014_ROOT" --archive-root "$RAW_HISTORY_ROOT"
```

Los archivos y resultados llevan hashes de sus entradas y salidas. El código no
conecta estas tablas al modelo productivo. `eligible_predeadline` permanece falso:
el enlace de identidad retrospectivo no acredita publicación antes del deadline.

Búsqueda adicional: ORBIX Research localizó el paper
[Time Series Modeling for Dream Team in Fantasy Premier League](https://arxiv.org/pdf/1909.12938),
que describe datos 2013/14–2015/16 pero no enlaza un archivo recuperable: su referencia
Kaggle es genérica y su procesamiento excluye jugadores. No se contabiliza cobertura
por esa referencia. [FPL Analytics 2015/16](https://www.fplanalytics.com/history1516.html)
conserva una tabla de resumen; su URL JSON pública referenciada por la página devuelve
HTTP 403 en esta auditoría. No se descargó ni se declara recuperada 2015/16.


## Gate G5: paquete verificable y recuperación parcial de 2015/16

[results-g5.json](results-g5.json) conserva el manifiesto del paquete, hashes,
cuarentenas y cobertura. Se adquirieron otros cinco archivos (4.996.406 bytes),
sin errores, con los commits de `pins-g5.json`.

- [Snapshot de clwatkins](https://github.com/clwatkins/fantasy_premier_league):
  17.373 etiquetas, 620 jugadores, 292/380 partidos (76,84%), GW1–30 parcial.
  Hay 88 partidos ausentes. Otras 71 filas no tienen marcador en el snapshot:
  se conservan en cuarentena y no se interpretan como no-apariciones. La suma
  de puntos observados coincide con el total del snapshot para sus 620 jugadores.
  El JSON original usa `web_name` como clave, por lo que no demuestra cobertura
  del universo completo ni preservación de homónimos. No es una temporada completa.
- [Snapshot de prathmesh](https://github.com/prathmesh/Fantasy-Premier-League-Points-Predictor):
  9.822 observaciones de 2014/15, 623 jugadores y 160 partidos, GW1–16. Todas
  coinciden con el histórico completo en jugador, fixture, jornada, minutos y puntos.
  Sus códigos oficiales resuelven 166 identidades adicionales, sin conflicto con
  las anteriores. No se suman estas filas como datos nuevos: son solapamiento.

El histórico completo 2014/15 conserva ahora 652 jugadores y 24.012 filas con
identidad oficial; resuelve 10.407/10.428 apariciones con minutos (99,80%). Quedan
59 jugadores, 864 filas y 21 apariciones sin código. La nueva salida vive separada
bajo `SNAPSHOT_ROOT/identity`; no se sobrescribe la evidencia G4.

```bash
python -m experiments.data_ground_truth.raw \
  --root "$SNAPSHOT_ROOT" --pins experiments/data_ground_truth/pins-g5.json
python -m experiments.data_ground_truth.snapshots \
  --root "$SNAPSHOT_ROOT" --archive-root "$RAW_HISTORY_ROOT" \
  --old-root "$FPL_2014_ROOT"
python -m experiments.data_ground_truth.training_dataset \
  --recent-root "$RAW_HISTORY_ROOT" --old-root "$FPL_2014_ROOT" \
  --identity-root "$SNAPSHOT_ROOT/identity" --output "$DATASET_ROOT"
```

El paquete de etiquetas de temporadas completas contiene **278.707 filas**.
La diferencia frente a las 278.766 filas raw es una cuarentena de 59 placeholders
cero de 2019/20: fixture 275 aparece en GW29 y nuevamente en GW39 después del
aplazamiento. Solo se excluye una observación anterior si todos sus resultados son
cero y existe una única observación que coincide con jornada y kickoff del fixture
finalizado en la fuente fijada. Una discrepancia positiva o evidencia insuficiente
aborta el build. Los bytes originales y las filas excluidas se conservan.

La partición es entrenamiento 2014/15 y 2016/17–2023/24 (221.355 filas), validación
2024/25 (27.605) y evaluación 2025/26 (29.747). Esta última ya fue usada en
investigación previa: **no se presenta como test nunca visto**. Los datos parciales
2015/16 quedan fuera del paquete de temporadas completas; están disponibles aparte
para un protocolo futuro que declare esa cobertura y su sesgo de selección.

Cada paquete tiene ID SHA-256, hashes de entradas, implementación y particiones,
CSV comprimido determinista, publicación atómica y verificación al cargar. Repetir
un build idéntico reutiliza la versión. `load_partition(package, split)` valida
el paquete entero antes de entregar datos. Los IDs oficiales se conservan; los
faltantes usan un namespace FPL por temporada para evitar uniones inventadas.
Se excluyen snapshots finales, precios, ownership y xP. Es un contrato de etiquetas,
no una matriz causal de features ni un replay de decisiones listo para promoción.

La siguiente brecha es recuperar los 88 partidos ausentes de 2015/16, completar
identidades y reconstruir evidencia de disponibilidad anterior al deadline. Los
resultados observados por sí solos no acreditan noticias, lesiones, precios,
calendario conocido, reglas de chips ni acciones legales en cada momento histórico.


## Gate G6: 2015/16 completa y doce temporadas consecutivas

La búsqueda ampliada encontró [mvbfontes/premierleaguedatasets](https://github.com/mvbfontes/premierleaguedatasets),
un archivo de respuestas de la API FPL por ID de jugador. `pins-g6.json` fija el
commit; se adquirieron 724 archivos / 2.795.465 bytes sin errores. Cada JSON debe
coincidir con el ID de su nombre de archivo, y los códigos oficiales deben ser únicos.
No se ejecuta código del repositorio fuente.

[results-g6.json](results-g6.json) verifica **24.741 observaciones, 723 jugadores,
38 jornadas y 380/380 partidos**. Incluye 750 observaciones adicionales de dobles
jornadas. Los puntos y trece componentes (minutos, goles, asistencias, porterías a
cero, goles concedidos, autogoles, penaltis, tarjetas, saves, bonus y BPS) suman
exactamente sus totales de temporada para cada jugador. No hay claves duplicadas
ni identidad oficial ausente.

Las 17.373 observaciones del snapshot parcial G5 coinciden en fixture, jugador,
jornada, minutos, puntos y código. G6 agrega los 88 partidos restantes, 7.368 filas
y 103 jugadores. El snapshot parcial se conserva como evidencia de reconciliación;
no se concatena al completo. Queda cerrado el hueco de resultados de 2015/16.

```bash
python -m experiments.data_ground_truth.raw \
  --root "$FPL_2015_ROOT" --pins experiments/data_ground_truth/pins-g6.json
python -m experiments.data_ground_truth.historical_2015 \
  --root "$FPL_2015_ROOT" --archive-root "$RAW_HISTORY_ROOT" \
  --snapshot-root "$SNAPSHOT_ROOT"
python -m experiments.data_ground_truth.training_dataset \
  --recent-root "$RAW_HISTORY_ROOT" --old-root "$FPL_2014_ROOT" \
  --identity-root "$SNAPSHOT_ROOT/identity" --season-2015-root "$FPL_2015_ROOT" \
  --output "$DATASET_ROOT"
```

El paquete `fpl-labels-v2` contiene **303.448 etiquetas** de doce temporadas
consecutivas (2014/15–2025/26): 246.096 para entrenamiento, 27.605 de validación y
29.747 de evaluación histórica ya utilizada. Mantiene las cuarentenas anteriores,
los IDs por temporada y la disponibilidad predeadline desconocida. El loader
contrasta la cobertura declarada de 2015/16 con las filas reales antes de incluirla.
Los paquetes G5 existentes permanecen verificables y no se sobrescriben.

Todavía quedan identidades 2014/15 sin resolver y fuentes predeadline por reconstruir.
La búsqueda anterior a 2014/15 sigue abierta. El paper primario
[The Wisdom of Smaller, Smarter Crowds](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/smart_crowds.pdf)
describe observaciones FPL 2012/13, pero el PDF no proporciona una descarga del
archivo de jugadores; esa referencia no se cuenta como cobertura recuperada.


## Gate G7: evidencia de identidad y códigos históricos

[results-g7.json](results-g7.json) documenta el cruce con los registros de plantillas
ya archivados. Para enlazar PL se exige nombre completo normalizado y club, candidato
único y ausencia de contradicción con códigos existentes. Se admite la transliteración
explícita Đ/đ → D/d o Dj/dj, sin distancia de edición. El campo `playerId` de squad se
contrasta contra `official_player_code` de observaciones; no se confunde con el
`playerId` nativo del archivo de partidos. Hay **226.031 filas conocidas corroboradas,
240 códigos recuperados y cero contradicciones** en ese cruce.

Quedan 1.770 filas PL sin código; 179.636 observaciones tienen identidad y minutos
dentro de rango (197 más que G4). Los minutos ausentes siguen ausentes y los valores
fuera de rango no se corrigen. Estas fuentes no constituyen evidencia estadística
independiente: son archivos complementarios con semántica explícita.

Para resolver FPL 2014/15 se exige un único código compatible con **todas las
apariciones con minutos**, coincidiendo fixture, club y nombre. Cada candidato
además debe estar corroborado por el registro de nombre completo/club o por otro
snapshot FPL con el mismo nombre, club y totales de minutos/puntos de 2014/15.
Un candidato ausente en cualquiera de las apariciones, ambiguo, o sin corroboración
no se asigna. No se relaja ni sobrescribe el procedimiento G4; G7 conserva su propia
evidencia y añade fuentes. La igualdad de minutos PL/FPL no es requisito de identidad,
y las diferencias observadas no se sobrescriben.

Se corroboran 434 identidades existentes y se añaden 13 jugadores / 190 filas.
El resultado alcanza **665 jugadores, 24.202 filas y las 10.428/10.428 apariciones
con minutos**. Quedan 46 jugadores sin código, 674 filas, todos sin apariciones.
Se mantienen IDs FPL acotados por temporada para esas filas.

También se encontró un cambio de código de Isaiah Brown: 81132 en la API archivada
2014/15 y 112516 en 2015/16. La equivalencia requiere nombres completos coincidentes
en ambos archivos FPL, mismo club, totales históricos y el código nuevo en el fixture
realizado. Se conserva `source_official_player_code=81132` y el código reconciliado
112516. No se permite actualizar una identidad conocida solo por apellido/club:
Luke y Donervon Daniels demuestran ese fallo. Tampoco basta el nombre completo:
los Adam Smith de distintos clubes no se fusionan.

```bash
python -m experiments.data_ground_truth.identity_registry \
  --archive-root "$RAW_HISTORY_ROOT" --snapshot-root "$SNAPSHOT_ROOT" \
  --season-2015-root "$FPL_2015_ROOT" --output "$IDENTITY_REGISTRY_ROOT"
python -m experiments.data_ground_truth.training_dataset \
  --recent-root "$RAW_HISTORY_ROOT" --old-root "$FPL_2014_ROOT" \
  --identity-root "$IDENTITY_REGISTRY_ROOT/identity" \
  --season-2015-root "$FPL_2015_ROOT" --output "$DATASET_ROOT"
```

El paquete `fpl-labels-v3` conserva las 303.448 etiquetas y las mismas particiones,
con identidad actualizada y código original explícito. G5/G6 y el histórico canónico
permanecen intactos. Estos enlaces retrospectivos no acreditan disponibilidad
predeadline. Queda por ampliar la reconciliación de códigos PL entre temporadas,
las identidades sin apariciones y las fuentes anteriores a 2014/15.


## Gate G8: archivos anteriores a 2014/15, todavía sin promover

La búsqueda amplió el inventario de 39 repositorios candidatos: 38 consultas
completadas y una fallida. [results-g8.json](results-g8.json) conserva revisiones
y hashes de inventarios. La extensión de archivo inicial no bastaba: aparecieron
bases `.db3` y volcados `.bson` además de CSV/JSON.

Se adquirieron **15 archivos / 37.857.224 bytes** de
[sjp4/differentialfpl](https://github.com/sjp4/differentialfpl), fijados en
`pins-g8.json`: ocho bases genéricas, un dump SQL, código documental del extractor,
README y licencia. No se adquieren las bases de equipos personales `DiffMoi` ni
se ejecutan Java, SQL o código de esa aplicación. No pertenece al legacy de MOVA.

La auditoría abre SQLite en modo de solo lectura e inmutable, desactiva el schema
confiable, comprueba integridad y exige tablas físicas conocidas. Conserva la
semántica de ID: la base inicial usa `player_fpl_id`; las siguientes usan el ID
interno `player_player_id`. Los cruces de totales usan el campo correspondiente de
`player_season`, nunca asumen que ambos namespaces sean iguales.

La base `diffgen16.db3` contiene estas filas con minutos y puntos no nulos:

| Temporada | Filas con ambas etiquetas almacenadas |
| --- | ---: |
| 2010/11 | 8.320 |
| 2011/12 | 9.462 |
| 2012/13 | 10.076 |
| 2013/14 | 10.389 |
| 2014/15 | 1.925 |
| 2015/16 | 0 |

Estas cifras **no prueban temporadas completas ni etiquetas reconciliadas**.
La base inicial 2010/11 tiene más cobertura que las posteriores, pero su GW38 es
un placeholder: 673 filas sin minutos ni puntos. En `diffgen16`, las 20.292 filas
2015/16 tampoco tienen resultados. Hay discrepancias entre sumas y snapshots de
totales en otras temporadas, que pueden reflejar cortes distintos y requieren
reconciliación. No se cuentan como nuevos ejemplos válidos ni se suman versiones
solapadas de la misma base.

Los NULL permanecen desconocidos. El extractor histórico omite algunos componentes
cero, pero eso no acredita que todo NULL de cualquier tabla/versión equivalga a cero.
La salida `staging/unreconciled_player_match.csv` usa una lista explícita de columnas,
excluye predicciones y métricas calculadas, y lleva `eligible_training=false`,
`eligible_predeadline=false` y `available_at` vacío.

```bash
python -m experiments.data_ground_truth.raw \
  --root "$DIFFERENTIAL_ROOT" --pins experiments/data_ground_truth/pins-g8.json
python -m experiments.data_ground_truth.differential_audit \
  --root "$DIFFERENTIAL_ROOT"
```

La adquisición ahora reutiliza inventarios ya capturados del mismo commit, y rechaza
inventarios truncados o de otra revisión. Esto permitió continuar cuando la API
pública de metadatos devolvió HTTP403, conservando el inventario previamente obtenido;
las descargas públicas de archivos y su verificación SHA-256 completaron sin errores.

El paquete validado sigue siendo `fpl-labels-v3`, 303.448 etiquetas y doce temporadas.
Los siguientes candidatos son el dump SQL GW38 ya archivado, que debe leerse como
literales sin ejecutar sus instrucciones, y los BSON de
[darrenvong/fpl-data-visualiser](https://github.com/darrenvong/fpl-data-visualiser),
aún no adquiridos. Sigue pendiente la propagación corroborada de IDs deportivos
entre temporadas. No hay promoción de modelo ni cambio de producción en este gate.

## Gate G9: recuperación SQL y auditoría BSON

[results-g9.json](results-g9.json) registra la extracción literal del SQL archivado
sin ejecutar sus instrucciones. Recupera **10.353 apariciones de 2010/11**, con
minutos y puntos presentes, 380 partidos y 38 jornadas. Las sumas cuadran con el
snapshot para los 543 jugadores con filas. El parser conserva strings y ceros,
rechaza expresiones y separa los INSERT de las transformaciones posteriores.
Estas últimas convertían ceros a NULL y eliminaban jugadores que no continuaban
en la siguiente temporada: las bases derivadas no eran una muestra completa.

La comprobación de cobertura ahora detecta jugadores con minutos de temporada
pero sin apariciones. En este dump hay uno: FPL ID 670, Ameobi, Newcastle,
9 minutos y 1 punto. El archivo deportivo identifica una aparición de Sammy
Ameobi en Chelsea–Newcastle del 15 de mayo de 2011, pero registra 8 minutos.
La [crónica del encuentro](https://www.skysports.com/football/chelsea-vs-newcastle-united/234069)
corrobora su entrada. No se inserta una etiqueta sintética ni se convierte este
indicio en una temporada completa. Además, el dump contiene apariciones positivas,
no el universo de jugadores elegibles con ceros: usarlo directamente para aprender
probabilidad de jugar introduciría sesgo de selección.

Se adquirieron **15 archivos / 56.492.039 bytes** de los snapshots BSON de
[darrenvong/fpl-data-visualiser](https://github.com/darrenvong/fpl-data-visualiser/tree/9e05f1270c91388c08f7c932ce03505b3d3871d1),
con revisión y hashes fijados. Los siete snapshots pertenecen a 2015/16:

| Snapshot | Filas crudas | Corroboradas contra 2015/16 | Filas en registros conflictivos |
| --- | ---: | ---: | ---: |
| current_gw | 19.946 | 19.946 | 0 |
| gw19 | 11.610 | 11.609 | 1 |
| gw26 | 16.231 | 16.046 | 185 |
| gw27 | 16.798 | 16.632 | 166 |
| gw30 | 18.547 | 18.547 | 0 |
| gw31 | 19.251 | 19.242 | 9 |
| gw32 | 19.946 | 19.946 | 0 |

Estas cifras se solapan entre snapshots y con la temporada ya validada: **no se
suman como nuevos ejemplos**. Cada conflicto conserva índice del documento, ID,
conteo y razones en el informe; el BSON original permanece inmutable. Se excluye
el documento completo cuando difieren identidad, partido, resultados o suma del
snapshot. También se reportan documentos vacíos. `gw31` incluye un documento
`Dummy` que comparte código con Stewart: ambos quedan en cuarentena por ambigüedad.
El timestamp del ObjectId es una afirmación del archivo, no prueba de publicación
antes del deadline. Ninguno de estos snapshots se habilita como feature causal.

```bash
python -m experiments.data_ground_truth.sql_archive --root "$DIFFERENTIAL_ROOT"
python -m experiments.data_ground_truth.raw \
  --root "$BSON_ROOT" --pins experiments/data_ground_truth/pins-g9.json
uv run --quiet --no-project --with pymongo==4.14.1 --with pandas==2.3.3 \
  python -m experiments.data_ground_truth.bson_archive \
  --root "$BSON_ROOT" --season-root "$SEASON_2015_ROOT"
```

La dependencia BSON se ejecuta aislada, sin conexión MongoDB. El benchmark mantiene
303.448 etiquetas, doce temporadas y el paquete v3. Quedan pendientes: reconciliar
los archivos anteriores a 2014/15 contra partidos e identidades, completar el universo
de no apariciones y acreditar disponibilidad temporal de features. Este gate mejora
la trazabilidad y detección de huecos; no acredita cierre de la brecha causal ni
promoción del modelo.

## Gate G10: cobertura de apariciones contrastada por partido

[results-g10.json](results-g10.json) cruza el SQL 2010/11 con el archivo deportivo
mediante equivalencias explícitas de nombres de clubes, par local/visitante único
y fecha local. Resuelve **380/380 partidos, sin discrepancias de fecha** y verifica
que cada aparición tenga el rival esperado. No equipara IDs numéricos entre fuentes.

De 760 lados de partido, **757 coinciden en número de apariciones**. Los tres
restantes quedan identificados por ID deportivo en el informe: Bolton en 321746
y 321761, Newcastle en 322021. FPL contiene 10.353 apariciones; la fuente deportiva
10.352 filas con minutos positivos y 3.303 con minutos desconocidos. Los NULL no
se convierten en no apariciones: ambas fuentes tienen limitaciones y sus totales
casi iguales no acreditan cobertura completa ni igualdad de jugadores.

La revisión de crónicas localiza dos omisiones deportivas: en Wigan–Bolton,
[Sky Sports documenta la entrada de Taylor por Petrov](https://www.skysports.com/football/wigan-athletic-vs-bolton-wanderers/215211),
pero el archivo deportivo deja a Taylor con minutos desconocidos y atribuye 90
a Petrov. En Bolton–Tottenham,
[la alineación de Sky Sports](https://www.skysports.com/football/bolton-vs-tottenham/teams/215196)
registra la entrada de Blake en el añadido, ausente de sus minutos deportivos.
Estas crónicas corroboran participación; no se usan para inventar minutos FPL
exactos ni puntos. El tercer caso sigue siendo la ausencia de Sammy Ameobi en
las filas SQL, ya detectada por el gate G9.

El cruce de nombre y presencia en todos los partidos genera candidatos únicos
para 524 jugadores / 9.998 apariciones. Quedan 19 sin candidato único; hay nombres
con iniciales o grafías distintas que no se resuelven mediante distancia difusa.
Son **candidatos de ID nativo deportivo**, no códigos oficiales promovidos. El
archivo deportivo incluye suplentes con minutos desconocidos; por eso este cruce
no constituye por sí solo corroboración de una aparición ni habilita entrenamiento.

```bash
python -m experiments.data_ground_truth.appearance_coverage \
  --sql-root "$DIFFERENTIAL_ROOT/sql-literals" \
  --sport-root "$RAW_HISTORY_ROOT" --out "$APPEARANCE_COVERAGE_ROOT"
```

Las entradas se verifican contra sus hashes G4/G9. El informe conserva los hashes
de `fixture_team_coverage.csv` e `identity_candidates.csv`, cuyos bytes permanecen
fuera de Git. Se mantiene el paquete v3 sin incorporar estas filas. El próximo
paso es corroborar identidad y apariciones concretas, incluyendo los casos de
Bolton, antes de considerar la reconstrucción del universo de no apariciones.

## Gate G11: códigos recuperados con IDs nativos y nombres completos

[results-g11.json](results-g11.json) mide la propagación retrospectiva de identidad
en las 17 temporadas deportivas. Antes de propagar se exige que ningún ID nativo
conocido corresponda a varios códigos oficiales. Cada recuperación exige el mismo
ID nativo, nombre completo normalizado idéntico y al menos dos partidos distintos
con código conocido; repeticiones del mismo partido no cuentan como dos testigos.
No usa coincidencia difusa ni propaga solo por apellido. Los testigos originales
se congelan antes del recorrido: una recuperación no alimenta otra.

Se recuperan **268 identidades de fila**: 59 en 2010/11, 65 en 2011/12, 3 en 2012/13,
38 en 2013/14, 33 en 2016/17, 32 en 2019/20 y 38 en 2020/21. Son siete temporadas.
El faltante de identidad deportivo baja de 1.770 a **1.502 filas**. De las recuperadas,
211 tienen minutos válidos: el total deportivo con identidad y minutos pasa de
179.636 a **179.847 observaciones**. Las otras 57 no se convierten en ceros ni en
etiquetas de minutos por el hecho de haber recuperado su identidad.

Los CSV conservan `source_official_player_code`, añaden `native_identity_recovered`
y permanecen fuera de Git. `evidence.json` enumera los partidos testigo por jugador
y temporada; su SHA-256 y los de entradas y salidas están en el informe. Todo sigue
con `eligible_predeadline=false`: enlazar retrospectivamente a una persona no prueba
que sus features fueran conocidas antes de decidir. Tampoco valida por sí solo los
524 candidatos FPL de G10: falta corroborar su correspondencia con el ID deportivo.

```bash
python -m experiments.data_ground_truth.native_identity \
  --registry-root "$IDENTITY_REGISTRY_ROOT" --out "$NATIVE_IDENTITY_ROOT"
```

El paquete FPL v3 conserva 303.448 etiquetas y doce temporadas. Este gate mejora
el archivo deportivo complementario; no sustituye minutos FPL, no incorpora datos
al canónico y no promueve un modelo.

La consulta del historial Git público de `Differential/Database` en la revisión
fijada devolvió un único commit inicial. Su respuesta está archivada con hash en
G11: esta ruta no aporta versiones previas para reparar 2011/12–2013/14. Hay que
contrastar las bases existentes o buscar otras fuentes, no asumir que un checkout
anterior de ese repositorio contiene temporadas más completas.

## Gate G12: identidades FPL 2010/11 corroboradas

El cruce histórico deja de ser solo una lista de candidatos: conserva las
apariciones FPL con identidad verificada cuando hay un código único en todos sus
partidos y al menos dos apariciones deportivas con minutos positivos. Rechaza
colisiones entre jugadores FPL, IDs deportivos contradictorios y filas duplicadas.
Los nombres con iniciales, como `Young L` y `Diouf EH`, se expanden mediante iniciales
exactas del nombre completo; no se corrigen grafías por distancia difusa.

Una segunda vía utiliza `season_history` del archivo FPL 2015/16: exige igualdad
de minutos y puntos de 2010/11, nombre completo y código corroborados por el registro
de partido. Esta evidencia independiente permite resolver algunos casos de una
sola aparición o de minutos deportivos desconocidos. El código mantiene los
minutos y puntos originales del SQL; nunca los sustituye por minutos deportivos.
La igualdad de totales se usa retrospectivamente para identidad, no como feature.

El resultado verifica **502 jugadores / 10.164 apariciones** (98,17% de las
10.353 filas SQL). Hay 153 jugadores corroborados también por los totales del
archivo FPL posterior. Quedan **41 jugadores / 189 filas** sin identidad verificada.
La medición y hashes están en [results-g12.json](results-g12.json). El artefacto
`appearances.csv` conserva también las filas no resueltas; `evidence.json` registra
los partidos y la vía de corroboración por jugador. Las entradas proceden de los
archivos SQL, deportivos G11 y JSON FPL 2015/16 verificados por hash.

```bash
python -m experiments.data_ground_truth.historical_identity \
  --sql-root "$DIFFERENTIAL_ROOT/sql-literals" \
  --sport-root "$RAW_HISTORY_ROOT" --native-root "$NATIVE_IDENTITY_ROOT" \
  --later-root "$SEASON_2015_ROOT" --out "$HISTORICAL_FPL_IDENTITY_ROOT"
```

La identidad verificada no resuelve el universo de no apariciones ni la fila
faltante de Sammy Ameobi. Se conserva `eligible_training=false` y
`eligible_predeadline=false`; no se integra este archivo como temporada completa
al paquete v3. Los siguientes pasos siguen siendo completar las apariciones y
el universo elegible, contrastar otras temporadas antiguas y acreditar causalidad.

## Gate G13: historial de jugador y solapamiento entre archivos

La comparación de versiones Differential de 2011/12–2013/14 utiliza claves de
jugador interno, temporada y partido. Unir las siete versiones no añade filas con
minutos y puntos respecto a la mejor versión individual: 9.462 en 2011/12,
10.076 en 2012/13 y 10.389 en 2013/14. No hay contradicciones entre los valores
no nulos comparados. Los NULL complementarios de dos versiones no se combinan
para fabricar una fila observada. La ausencia de contradicción tampoco prueba
que una versión contenga todos los partidos de cada jugador.

El JSON FPL 2015/16 aporta 1.976 registros jugador-temporada de 2006/07–2014/15,
extraídos con código, minutos, puntos y hash del registro fuente. Para 2014/15,
441 coinciden con las sumas de etiquetas reconciliadas, sin diferencias. Otros
23 tienen cero minutos y puntos y no aparecen en esa referencia: no prueban que
estuvieran inscritos ni que fueran elegibles en cada partido de 2014/15.

La adquisición adicional de Vaastav usa el inventario completo de la revisión
`9779cdbc0c07f6c900c2d0c181ddf6bb9c800f88`, selecciona exclusivamente
`data/2016-17`…`data/2025-26/players/*/history.csv` y conserva bytes por SHA-256.
Se ejecuta por la misma primitiva GET, con cuatro trabajadores y caché verificable.
No selecciona la temporada abierta 2026/27 en este gate.

La auditoría normaliza únicamente código, temporada, minutos y puntos. Los demás
componentes permanecen en los CSV crudos; no se interpreta un cero histórico de
una métrica introducida posteriormente como medición real. Cada registro normalizado
conserva ruta y hash fuente. Un jugador-temporada con resultados contradictorios
queda fuera del consenso, sin elegir automáticamente la versión más nueva ni la
mayoría. Las copias de API no constituyen mediciones independientes.

La adquisición completó **5.978 archivos / 3.864.197 bytes**, todos parseados,
sin errores de descarga ni archivos en cuarentena. Al combinarlos con los 1.976
registros anteriores hay 25.479 registros fuente y **8.284 claves jugador-temporada
únicas**, de 2006/07 a 2024/25: **6.308 claves adicionales** respecto al archivo
anterior. Ninguna clave comparada presentó contradicciones de minutos o puntos.
Por ejemplo, 2010/11 pasa de 182 a 229 jugadores con totales; 2011/12 de 222 a 267,
2012/13 de 291 a 339 y 2013/14 de 356 a 412. Los detalles y hashes están en
[results-g13.json](results-g13.json). Los datos no publicados permanecen en
`source_observations.csv`, `consensus_totals.csv` y la auditoría por archivo.

Los totales son **observaciones jugador-temporada**, no filas de gameweek. No se
suman al benchmark de 303.448 etiquetas ni acreditan temporadas con población
completa. Se conservan flags de entrenamiento/predeadline desactivados y se
explicita el sesgo de jugadores presentes en cada archivo posterior.

```bash
python -m experiments.data_ground_truth.season_evidence \
  --database-root "$DIFFERENTIAL_ROOT" --later-root "$SEASON_2015_ROOT" \
  --identity-root "$IDENTITY_REGISTRY_ROOT" --out "$SEASON_EVIDENCE_ROOT"
python -m experiments.data_ground_truth.history_archive \
  --root "$PLAYER_HISTORIES_ROOT" --inventory "$VAASTAV_PINNED_INVENTORY" \
  --revision 9779cdbc0c07f6c900c2d0c181ddf6bb9c800f88
python -m experiments.data_ground_truth.history_consensus \
  --root "$PLAYER_HISTORIES_ROOT" --prior-root "$SEASON_EVIDENCE_ROOT" \
  --out "$HISTORY_CONSENSUS_ROOT"
```
