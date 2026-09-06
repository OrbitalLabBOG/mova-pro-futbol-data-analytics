---
type: research
name: MOVA historical raw data and ground truth audit
updated: 2026-09-06
status: experimental
---

# Histórico crudo y ground truth: raw-history-v1

Corte acumulado al 6 de septiembre de 2026 (Colombia). Este experimento adquiere y audita
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

## Gate G14: todos los historiales del inventario y correcciones verificadas

[results-g14.json](results-g14.json) incorpora los **517 historiales de jugadores**
de la carpeta 2026/27: 430.549 bytes, cero errores y todos parseados. Junto a G13
se han adquirido los **6.495 `history.csv` de jugadores** del inventario fijado;
el otro historial pertenece a un equipo personal y no es parte de este dataset.
La carpeta del snapshot puede corresponder a la temporada abierta mientras sus
filas describen temporadas anteriores. El consenso admite solo temporadas hasta
2025/26; una fila 2026/27 queda fuera y se conserva separada. Este lote no contenía
filas de la temporada abierta.

Se conservan los 25.479 registros fuente anteriores y se añaden 2.062: el consenso
alcanza **8.786 claves jugador-temporada de 2006/07–2025/26**, 502 adicionales,
sin contradicciones entre historiales. Incluye 468 totales 2025/26. Las claves
conflictivas de una versión anterior también se preservan al extender el archivo,
sin reemplazarlas por un consenso previo que las hubiera omitido.

El contraste con las sumas de etiquetas por jornada encontró dos errores en los
CSV combinados de Vaastav. Se adquirieron los CSV individuales en la misma revisión
y se verificaron jugador/código, conjunto de partidos, jornada, fecha y sumas de
**todos los componentes normalizados** contra `players_raw.csv` de esa temporada:

| Jugador | Temporada / fixture FPL | Campo | Combinado anterior | CSV individual corroborado |
| --- | --- | --- | ---: | ---: |
| Bernd Leno | 2018/19 · 61 | minutos | 42 | 45 |
| Evan Ferguson | 2024/25 · 239 | minutos | 0 | 17 |
| Evan Ferguson | 2024/25 · 239 | puntos | 0 | 1 |
| Evan Ferguson | 2024/25 · 239 | goles concedidos | 0 | 2 |

Son correcciones de fuente, no etiquetas sintetizadas a partir de reglas ni de
minutos deportivos. El paquete de G14 es **`fpl-labels-v4`**, ID
`f69c13a09b55c131fcae3e53bb09da43a827f31f58a501eef7a3c60239857456`:
303.448 filas, doce temporadas y las mismas particiones. Su manifiesto registra
cada campo anterior/nuevo, fuentes, código de reparación y hashes. El paquete v3
y los CSV combinados originales permanecen intactos; el canónico y el VPS no se
modifican. Los experimentos comparables deben fijar el mismo dataset ID.

Después de corregir, **6.934 totales jugador-temporada** coinciden con la suma de
filas con identidad oficial de las doce particiones: cero diferencias de minutos
o puntos en esa comparación. Hay registros fuera del rango y sin correspondencia;
no se convierten en prueba de población completa ni de inscripción histórica.
Sigue pendiente contrastar sistemáticamente los CSV individuales restantes, además
de completar el histórico anterior a 2014/15 y acreditar disponibilidad predeadline.

```bash
python -m experiments.data_ground_truth.history_archive \
  --root "$PLAYER_HISTORIES_2026_ROOT" --inventory "$VAASTAV_PINNED_INVENTORY" \
  --revision 9779cdbc0c07f6c900c2d0c181ddf6bb9c800f88 --snapshot-season 2026-27
python -m experiments.data_ground_truth.history_consensus \
  --root "$PLAYER_HISTORIES_2026_ROOT" --prior-root "$HISTORY_CONSENSUS_ROOT" \
  --out "$HISTORY_CONSENSUS_V2_ROOT" --closed-through 2025
python -m experiments.data_ground_truth.training_dataset \
  --recent-root "$RAW_HISTORY_ROOT" --old-root "$HISTORICAL_2014_ROOT" \
  --identity-root "$IDENTITY_REGISTRY_ROOT/identity" \
  --season-2015-root "$SEASON_2015_ROOT" --repairs-root "$LABEL_REPAIRS_ROOT" \
  --output "$TRAINING_DATASETS_ROOT"
python -m experiments.data_ground_truth.history_reference \
  --consensus-root "$HISTORY_CONSENSUS_V2_ROOT" --package "$LABELS_V4_PACKAGE" \
  --out "$HISTORY_REFERENCE_ROOT"
```

`LABEL_REPAIRS_ROOT` contiene el manifiesto y objetos adquiridos de
`data/2018-19/players/Bernd_Leno_2/gw.csv` y
`data/2024-25/players/Evan_Ferguson_123/gw.csv`, en la revisión Vaastav fijada.
Los hashes exactos quedan en las reparaciones del manifiesto v4 y en G14.


## Gate G15: cobertura individual y separación de entidades

[results-g15.json](results-g15.json) registra la adquisición de **7.365 CSV por
jugador y partido**, **39.523.460 bytes**, sin errores. Es el 100% de las rutas
`players/*/gw.csv` de 2016/17–2025/26 en el inventario Vaastav fijado. Todos los
elementos presentes en las diez particiones de referencia tienen un archivo
comparado; esto no prueba el universo histórico de jugadores elegibles.

El contraste contra v4 comprueba claves, jornada, fecha, minutos, puntos y doce
componentes. Detecta un BPS distinto: Cucho Hernández, 2021/22, fixture 8,
**28 → 29**. Su archivo individual concuerda en claves, fechas y sumas de todos
los componentes con `players_raw.csv`; se incorpora con el mismo gate estricto
de reparación de G14. No cambia sus puntos FPL.

El paquete **fpl-labels-v5**, ID
`1d111a458c9074fcd7ec2da516e82d9d1984600f6f057716112b92e855240df4`,
contiene **303.126 filas de jugadores** en doce temporadas. Conserva las cuatro
correcciones de G14 y añade la de BPS. Se separan **322 filas de Assistant Manager**
de 2024/25 en un archivo con hash propio, sin habilitación para entrenar jugadores.
Las particiones principales suman 246.096 filas train, 27.283 validation y 29.747
evaluation. Los artefactos previos siguen disponibles. Los 20 elementos de manager
son slots FPL de temporada: no equivalen necesariamente a veinte identidades
humanas estables (el elemento 748 aparece como Ivan Juric y Simon Rusk).

La auditoría por archivo cuenta **180 filas solo en la referencia y 15 solo en
el individual**. No son diferencias de población únicas: hay siete pares de rutas
con el mismo elemento-temporada, incluyendo archivos antiguos incompletos tras
cambios de nombre y el slot de entrenador mencionado. Los 15 registros adicionales
individuales tienen cero minutos y puntos; no se incorporan como negativos sin
resolver elegibilidad y pertenencia al club en ese momento. Se conservan todos
los originales, sin fusionar automáticamente los archivos por nombre o recencia.

Hay **78 discrepancias de kickoff**, todas del fixture 263 de 2021/22:
15:00 UTC en la referencia y 15:30 UTC en los individuales. El `fixtures.csv`
archivado también indica 15:30 UTC. Esta versión registra la evidencia pero no
modifica las fechas: su corrección requiere un gate propio y no acredita cuándo
se conoció el retraso. Seis archivos individuales discrepan en totales finales;
son archivos incompletos de esos pares de rutas, no seis nuevos errores probados
del GT combinado. La adquisición exhaustiva no implica cero discrepancias.

```bash
python -m experiments.data_ground_truth.history_archive \
  --root "$PLAYER_GAMEWEEKS_ROOT" --inventory "$VAASTAV_PINNED_INVENTORY" \
  --revision 9779cdbc0c07f6c900c2d0c181ddf6bb9c800f88 --artifact gw
python -m experiments.data_ground_truth.individual_audit \
  --root "$PLAYER_GAMEWEEKS_ROOT" --recent-root "$RAW_HISTORY_ROOT" \
  --package "$LABELS_V4_PACKAGE" --out "$INDIVIDUAL_AUDIT_ROOT"
python -m experiments.data_ground_truth.training_dataset \
  --recent-root "$RAW_HISTORY_ROOT" --old-root "$HISTORICAL_2014_ROOT" \
  --identity-root "$IDENTITY_REGISTRY_ROOT/identity" \
  --season-2015-root "$SEASON_2015_ROOT" --repairs-root "$LABEL_REPAIRS_V2_ROOT" \
  --separate-managers --output "$TRAINING_DATASETS_ROOT"
```

`LABEL_REPAIRS_V2_ROOT` selecciona del archivo adquirido los dos CSV de G14 más
`data/2021-22/players/Juan Camilo_Hernández Suárez_472/gw.csv`. Sus bytes y hashes
originales se preservan; el manifiesto v5 registra la evidencia de cada cambio.
El verificador comprueba también integridad y exclusión de entrenamiento del
archivo de managers. `load_partition` devuelve únicamente jugadores para v5.

G15 no añade temporadas completas. Siguen pendientes población e identidades
anteriores a 2014/15 y disponibilidad histórica predeadline de las features.
El siguiente gate debe reconciliar claves y fechas con evidencia temporal,
sin convertir ceros ambiguos en no apariciones observadas. Después podrá medirse
cobertura de estados de decisión para precios, lesiones, traspasos y chips.

## Gate G16: snapshots históricos de bootstrap

La fuente adicional [Randdalf/fplcache](https://github.com/Randdalf/fplcache),
revisión `dda55fefed3104e428a32e4a1f278d42f3c03407`, contiene **7.837 capturas
comprimidas / 867.734.672 bytes**, con fechas declaradas entre 2021-04-18 16:41
y 2026-09-05 20:12. La adquisición y auditoría completaron los 7.837 snapshots sin errores. Se
adquirieron también README, licencia, script de captura y workflow como evidencia
de procedencia; los scripts externos no se ejecutan. Hay 6.907 objetos de snapshot
distintos por hash: rutas distintas pueden repetir bytes.

`bootstrap_archive` guarda todos los bytes por hash, verifica tamaños contra el
inventario y reutiliza objetos verificados para reanudar. Mantiene la fecha del
nombre en `source_claimed_at`, sin zona: el código fuente usa `datetime.today()`.
`available_at` sigue desconocido. El workflow programado y una fecha de archivo
no certifican por sí solos disponibilidad histórica anterior al deadline.

`bootstrap_audit` descomprime con límites, comprueba población y calendario,
separa jugadores de managers y mide presencia/no nulidad de precios, club,
posición, estado, noticias, probabilidad de jugar y métricas retrospectivas.
Los NULL de disponibilidad no se convierten en disponibilidad segura. Mide también
intervalos entre capturas y candidatos dentro de 48 horas de un deadline bajo una
**hipótesis explícita de reloj UTC**, únicamente para explorar cobertura. Ningún
candidato recibe `eligible_predeadline=true`. La temporada se deriva del deadline
de GW1 del contenido, no del año del directorio; la temporada abierta se conserva
separada por su identificador y no cuenta como nuevas etiquetas completas.

```bash
python -m experiments.data_ground_truth.bootstrap_archive \
  --root "$BOOTSTRAP_RAW_ROOT" --inventory "$BOOTSTRAP_PINNED_INVENTORY" \
  --revision dda55fefed3104e428a32e4a1f278d42f3c03407
python -m experiments.data_ground_truth.bootstrap_audit \
  --root "$BOOTSTRAP_RAW_ROOT" --out "$BOOTSTRAP_AUDIT_ROOT"
```

[results-g16.json](results-g16.json) conserva la cobertura medida, hashes y pruebas
de procedencia. La adquisición contiene 7.841 archivos, incluidos cuatro de
procedencia, sin errores; el auditor leyó las 7.837 capturas, sin errores.

| Temporada del contenido | Snapshots | Filas jugador-snapshot | Deadlines con candidato nominal ≤48h |
| --- | ---: | ---: | --- |
| 2020/21 | 257 | 181.040 | 6: GW33–38 |
| 2021/22 | 1.511 | 975.944 | 38: GW1–38 |
| 2022/23 | 1.458 | 999.028 | 38: GW1–38 |
| 2023/24 | 1.510 | 1.165.413 | 38: GW1–38 |
| 2024/25 | 1.471 | 1.051.944 | 38: GW1–38 |
| 2025/26 | 1.459 | 1.143.248 | 38: GW1–38 |
| 2026/27 abierta | 171 | 100.857 | 3: GW1–3 |

Son **5.617.474 filas jugador-snapshot**, no resultados de partido independientes.
Hay además **14.240 filas de manager**, todas de 2024/25. Código, precio, club,
posición y estado están presentes y no nulos en todas las filas de jugadores.
La probabilidad de jugar la siguiente jornada está presente pero solo es no nula
en 3.404.562 filas; el auditor conserva esa diferencia sin imputar 100%.
xG/xA no aparecen en las capturas 2020/21–2021/22 y tienen cobertura parcial en
2022/23. No se rellenan con cero para aparentar un esquema homogéneo.

Hay 199 candidatos nominales en total, incluidos seis de la temporada inicial
parcial y tres de la abierta. La selección usa exclusivamente el calendario que
contiene cada snapshot, bajo hipótesis UTC; no sustituye el calendario conocido
en esa fecha por la programación final. Sigue habiendo **cero snapshots con
admisión predeadline verificada**. No se transfieren automáticamente a Store.

La comprobación de una captura de 2024-08-16 12:38 encontró un único commit con
fecha 12:38:36 UTC y mensaje consistente, sin firma verificada. La consulta de
GitHub Actions para ese día devolvió cero ejecuciones. Esa coherencia no acredita
por sí sola publicación histórica ni resuelve todo el archivo. Se guardan ambas
respuestas en el directorio externo de descubrimiento.

También se inspeccionó la página histórica 2013/14 de fplanalytics.com: enlaza un
JSON en S3 que respondió HTTP 403 tras cinco intentos. No se adquirieron sus datos
ni se cuentan como una nueva temporada disponible.

El siguiente gate debe validar tipos/unidades e identidades por snapshot y
establecer el contrato temporal de admisión para los candidatos nominales,
incluyendo revisiones de calendario y las limitaciones de procedencia. El GT v5
sigue vigente; G16 no modifica sus filas ni el runtime. Los historiales anteriores
a 2014/15 y el universo elegible pendiente siguen dentro del alcance de investigación.

## Gate G17: contrato de estados e identidad de los candidatos nominales

[results-g17.json](results-g17.json) valida y normaliza los **199 snapshots
seleccionados por G16**, no todo el archivo de 7.837 capturas. Se comprueban hashes,
calendario del snapshot, IDs, código de jugador, club presente en el mismo
snapshot, posición, precio entero en décimas de GBP y porcentajes finitos en
0–100. Los booleanos opcionales rechazan strings y conservan por separado presencia
y valor nulo. No se convierten noticias ausentes ni probabilidades nulas en
certeza de disponibilidad. El estado `a` no equivale automáticamente a elegibilidad.

Los artefactos contienen **143.718 filas de jugadores** y **320 de managers** en
archivos separados (`player_states.csv.gz` y `manager_states.csv.gz`). Las 141.851
filas de jugadores de temporadas cerradas admitidas coinciden por elemento/código
con GT v5. Las 1.867 de 2026/27 llevan scope abierto y referencia no disponible;
no se validan contra una temporada cerrada de otro año. Los managers conservan
`source_element_code`, sin atribuirles un código de identidad de jugador.

Dos filas se conservan en `rejected.json` por conflicto de código en GW1 2022/23:

| Elemento | Nombre observado | Código del snapshot | Código GT final |
| --- | --- | ---: | ---: |
| 546 | Luke Harris | 536122 | 515024 |
| 558 | Hugo Bueno | 530332 | 490721 |

No se reemplazan códigos por coincidencia de nombre. La cuarentena conserva
ambos códigos, deadline y hash del snapshot; los bytes originales permanecen
archivados. Esto describe una discrepancia entre fuentes, no prueba que el estado
histórico original fuera inválido. Queda pendiente corroborar su continuidad.

`can_select`, `can_transact` y `removed` faltan en todos los candidatos de
2020/21–2023/24 y tienen presencia parcial en 2024/25. `has_temporary_code` aparece
aún más tarde dentro de esa temporada. En total, **94.980 filas de jugadores**
carecen de valor conocido de `can_select`; no se les asigna true ni false.
La presencia en el roster publicado, selección, posibilidad de transacción y
estado de lesión son hechos distintos. El paquete conserva sus flags originales
para investigar el universo elegible, sin reconstruirlo por una regla inventada.

```bash
python -m experiments.data_ground_truth.bootstrap_state \
  --root "$BOOTSTRAP_RAW_ROOT" --audit-root "$BOOTSTRAP_AUDIT_ROOT" \
  --package "$LABELS_V5_PACKAGE" --out "$BOOTSTRAP_STATE_ROOT"
```

El reporte registra hashes del manifiesto raw, candidatos, GT de referencia,
implementación y artefactos. Cada fila conserva hash de snapshot, temporada,
jornada, deadline y fecha declarada. `available_at` permanece desconocido;
`eligible_predeadline` y `eligible_training` permanecen false. No se convierte
este staging en un benchmark causal ni se modifica el GT v5 o producción.
Los siguientes pasos son corroborar las dos transiciones de código y definir
admisión temporal explícita, conservando la distinción entre evidencia de fuente
y disponibilidad verificada. Los históricos antiguos incompletos siguen pendientes.

## Gate G18: variantes de identidad en todo el archivo bootstrap

`bootstrap_identity` examina todos los snapshots adquiridos, agrupando las
observaciones por temporada y elemento FPL. Conserva cada variante de código,
nombre y posición, los clubes observados y testigos con ruta/hash para la primera
y última aparición. Valida el snapshot completo antes de incorporar testigos:
una fila inválida no deja observaciones parciales en el registro. Los cambios de
código y nombre se miden por separado; no se fusionan personas automáticamente.

La corrida completa examinó 7.837 snapshots sin errores y observó 5.391
claves temporada-elemento, incluidas veinte de manager en 2024/25. Encontró cuatro
claves con cambios de código y trece con cambios de nombre. No encontró un mismo
código usado por más de un elemento dentro de una misma temporada. Esto no prueba
unicidad universal del proveedor ni identidad personal estable a través de años.

| Temporada / elemento | Variantes observadas | Naturaleza que debe investigarse |
| --- | --- | --- |
| 2022/23 · 546 | Luke Harris: 536122 → 515024 | Cambio de código con nombre conservado |
| 2022/23 · 558 | Hugo Bueno López: 530332 → 490721 | Cambio de código con nombre conservado |
| 2023/24 · 120 | Yegor Yarmolyuk: 601975 → 508395; después Yarmoliuk | Código y escritura del nombre cambian en momentos distintos |
| 2024/25 · 748 | Ivan Juric 100045653 → Simon Rusk 100047426 | Sustitución de persona en un puesto de manager |

Harris conserva su código anterior en catorce snapshots del 3–6 de agosto de
2022; el nuevo aparece desde el 7 de agosto. Bueno conserva el anterior en trece
snapshots del 3–6 de agosto y cambia durante el 6 de agosto. Yarmolyuk cambia
código durante julio de 2023, antes de GW1; la modificación de escritura llega en
noviembre. Las fechas son las declaradas por el archivo, sin admisión predeadline.

El caso del manager impide interpretar cualquier cambio de código como un alias
personal. La ausencia de colisiones también es solo una propiedad del archivo
observado. Primera/última observación no son intervalos continuos de vigencia.
No se aplican reparaciones de identidad a G17 ni se altera el GT v5 con este gate.

```bash
python -m experiments.data_ground_truth.bootstrap_identity \
  --root "$BOOTSTRAP_RAW_ROOT" --out "$BOOTSTRAP_IDENTITY_ROOT"
```

[results-g18.json](results-g18.json) conserva métricas, cambios y hashes. El registro
detallado, colisiones e incidencias permanecen fuera de Git. La corrida final con
validación previa de todo el snapshot reprodujo exactamente los hashes de los
artefactos de la primera corrida; ambas tuvieron cero errores. Queda pendiente corroborar los alias de jugadores por
una regla explícita y trazable, distinguiéndolos de sustituciones de personas.

## Gate G19: alias de jugadores corroborados y estados recuperados

[results-g19.json](results-g19.json) incorpora una regla explícita para normalizar
cambios de código dentro del mismo elemento FPL y temporada. Exige exactamente
dos códigos, un código final único en GT v5, ausencia de colisiones observadas,
secuencia temporal sin solapamiento, mismo nombre y posición en el límite del
cambio, clubes observados compatibles y al menos dos objetos distintos a cada
lado. Además exige dos fechas de aparición positiva coincidentes entre las
etiquetas FPL y el archivo de partidos, usando fecha local británica para FPL.
No iguala IDs de fixture de proveedores distintos ni sustituye minutos FPL por
minutos deportivos. La corroboración es retrospectiva y no una feature futura.

Se corroboraron tres alias acotados: Harris (3 fechas de aparición coincidentes),
Bueno (21) y Yarmolyuk/Yarmoliuk (27). El cambio Juric→Rusk se excluye como
sustitución de manager. Los testigos completos y hashes quedan en `aliases.json`
y su reporte. No se crea un diccionario universal código-antiguo→persona: cada
aplicación exige temporada, elemento, código fuente y una observación dentro del
rango documentado. Ese rango limita el uso; no prueba continuidad entre capturas.

Con `--aliases-root`, el generador produce el contrato `bootstrap-state-v2` y
conserva `source_code` e `identity_alias_applied` en cada fila. Recupera las dos
filas de GW1 2022/23 de G17: Harris mantiene precio 45 décimas de GBP y Bueno 40;
sus códigos de origen quedan junto a los normalizados. El alias de Yarmoliuk no
se aplica a los 199 candidatos porque cambió antes de GW1.

Resultado: **143.720 estados de jugadores**, **320 managers separados**, dos filas
recuperadas y cero filas rechazadas en estos 199 candidatos. Se comprobó que todos
los campos anteriores de las 143.718 filas previas son idénticos. Hay ahora 94.982
valores de `can_select` desconocidos, porque las dos filas recuperadas tampoco
contenían esa señal. La equivalencia de identidad no resuelve elegibilidad.

```bash
python -m experiments.data_ground_truth.bootstrap_aliases \
  --identity-root "$BOOTSTRAP_IDENTITY_ROOT" --sport-root "$IDENTITY_REGISTRY_ROOT" \
  --package "$LABELS_V5_PACKAGE" --out "$BOOTSTRAP_ALIASES_ROOT"
python -m experiments.data_ground_truth.bootstrap_state \
  --root "$BOOTSTRAP_RAW_ROOT" --audit-root "$BOOTSTRAP_AUDIT_ROOT" \
  --package "$LABELS_V5_PACKAGE" --aliases-root "$BOOTSTRAP_ALIASES_ROOT" \
  --out "$BOOTSTRAP_STATE_V2_ROOT"
```

El consumidor CSV debe leer los booleanos opcionales como nullable boolean,
conservando los vacíos; no confiar en inferencia automática de pandas ni convertir
NULL a true/false. G19 conserva el modo sin alias, los paquetes anteriores y los
raw originales. Todos los estados siguen con admisión temporal y entrenamiento
desactivados. GT v5 y producción no cambian. Siguen pendientes el contrato temporal,
los 78 kickoffs discrepantes de G15 y el universo histórico antiguo incompleto.

## Gate G20: procedencia Git y publicación externa de snapshots

`bootstrap_time` contrasta los bytes comprimidos de los 7.837 snapshots con el
SHA-1 del objeto Git del inventario fijado. Examina un export del historial Git
completo, sin nombres ni correos de autores, y encuentra una sola adición por
archivo, sin modificaciones posteriores registradas. Los relojes declarados en
las rutas, interpretados explícitamente como UTC, preceden al commit entre 0 y
62 segundos. Los 199 candidatos tienen commit anterior al deadline y coincidencia
entre fecha de autor y committer. Estos relojes pertenecen a la fuente: por sí
solos no acreditan publicación histórica y no activan admisión temporal.

`publication_archive` descarga los archivos horarios de
[GH Archive](https://www.gharchive.org/), que preserva eventos públicos de GitHub.
Busca `PushEvent` del nombre e ID exactos de `Randdalf/fplcache` y exige que el SHA
del commit candidato aparezca como `head` o en su lista de commits. Solo admite
como testigo un evento público fechado entre el commit y el deadline. Su fecha
constituye un límite superior conservador de publicación, no la hora exacta de
captura ni una garantía de exactitud de cada campo. Un evento ausente no demuestra
que el archivo no estuviera publicado.

Se conservan URL, tamaño y hash del archivo horario, fecha de descarga y
Last-Modified cuando existe; solo se retienen los eventos originales del
repositorio investigado. Los demás eventos se descartan. Las horas se procesan
con cuatro workers y cache verificable; las URLs usan hora sin cero inicial.
`publication_coverage` vuelve a verificar hashes, identidad del repositorio,
proyección exacta de cada evento, derivación de cada testigo y correspondencia
con el hash/deadline de los estados G19. Mide jornadas y filas cubiertas por
temporada. El testigo vive separado: no reescribe los estados G19 ni activa
entrenamiento, integración con `Store` o promoción de modelos.

```bash
# Exportar desde el clon completo del repositorio fuente fijado:
git log --format='commit%x09%H%x09%cI%x09%aI' --raw --no-abbrev --no-renames \
  dda55fefed3104e428a32e4a1f278d42f3c03407 -- cache/ > "$BOOTSTRAP_GIT_LOG"
python -m experiments.data_ground_truth.bootstrap_time \
  --root "$BOOTSTRAP_RAW_ROOT" --log "$BOOTSTRAP_GIT_LOG" \
  --audit-root "$BOOTSTRAP_AUDIT_ROOT" --out "$BOOTSTRAP_TIME_ROOT"
python -m experiments.data_ground_truth.publication_archive \
  --root "$PUBLICATION_ARCHIVE_ROOT" --provenance-root "$BOOTSTRAP_TIME_ROOT"
python -m experiments.data_ground_truth.publication_coverage \
  --archive-root "$PUBLICATION_ARCHIVE_ROOT" --provenance-root "$BOOTSTRAP_TIME_ROOT" \
  --state-root "$BOOTSTRAP_STATE_V2_ROOT" --out "$PUBLICATION_COVERAGE_ROOT"
```

Los resultados y límites medidos se conservan en [results-g20.json](results-g20.json).
Los archivos raw y las evidencias por evento quedan fuera de Git. La publicación
no resuelve los flags de selección desconocidos, las reglas históricas de chips,
los calendarios completos conocidos en cada fecha ni la falta de estados de las
primeras temporadas del GT. El paquete de etiquetas v5 conserva su versión.

Resultado de la corrida: **198/199 horas adquiridas**, 12.415.091.475 bytes
comprimidos procesados, **164/199 deadlines con testigo** (82,4%). Sus snapshots
contienen **117.195/143.720 filas de jugadores** (81,5%) y los 320 managers.
Estas son filas de estado por jornada; no nuevas observaciones independientes
ni nuevas temporadas de etiquetas.

| Temporada | Candidatos | Deadlines corroborados | Filas jugador corroboradas |
| --- | ---: | ---: | ---: |
| 2020/21, parcial GW33–38 | 6 | 6 | 4.191 |
| 2021/22 | 38 | 36 | 23.826 |
| 2022/23 | 38 | 37 | 25.438 |
| 2023/24 | 38 | 34 | 26.507 |
| 2024/25 | 38 | 38 | 27.159 |
| 2025/26 | 38 | 13 | 10.074 |
| 2026/27, abierta GW1–3 | 3 | 0 | 0 |

Quedan 35 candidatos sin testigo: una hora con HTTP 404 (GW9 2021/22), confirmado
al reintentar, y 34 horas descargadas sin PushEvent del repositorio objetivo.
Consultar también la hora siguiente para GW26 2021/22 y GW33 2022/23 no añadió
evidencia. No se atribuye la ausencia a una causa no verificada. El comando de
adquisición terminó con exit 1 por el 404; la auditoría posterior completó y
verificó explícitamente la cobertura parcial. La suite local obtuvo 1.453 passed,
1 skipped y 79 deselected. No debe comunicarse este gate como adquisición completa.

El siguiente gate debe buscar testigos alternativos o capturas anteriores para
esos huecos, priorizando 2025/26, y definir la admisión del estado junto con sus
campos desconocidos. Una temporada con 38 testigos bootstrap todavía necesita
reglas de juego, calendario conocido, transiciones y etiquetas compatibles para
constituir un benchmark estratégico completo.

## Gate G21: capturas anteriores para cerrar huecos de temporadas terminadas

G21 busca alternativas para los 35 deadlines sin testigo en G20. El plan fija
241 capturas anteriores dentro de 48 horas; exige una única adición Git, relojes
coherentes y el mismo deadline en el calendario del propio snapshot. Examina de
más reciente a más antigua y deja de consultar alternativas de una jornada al
hallar un PushEvent público del commit exacto anterior al deadline. Esta selección
usa evidencia de publicación, sin mirar los resultados deportivos.

La corrida completó siete rondas, adquirió **85 horas** (3.211.301.171 bytes
comprimidos) y encontró **32 testigos nuevos**. Una hora adicional no pudo
adquirirse; su error queda registrado y el proceso devuelve exit 1. La búsqueda
continuó con capturas anteriores de esa jornada y consiguió corroborarla. No se
convierte un error de descarga en evidencia negativa ni se repiten horas ya
verificadas dentro de una corrida. La cache permite reanudar.

| Temporada | Deadlines corroborados G20 → G21 | Capturas sustituidas |
| --- | ---: | ---: |
| 2020/21, GW33–38 | 6 → 6 | 0 |
| 2021/22 | 36 → 38 | 2 |
| 2022/23 | 37 → 38 | 1 |
| 2023/24 | 34 → 38 | 4 |
| 2024/25 | 38 → 38 | 0 |
| 2025/26 | 13 → 38 | 25 |
| 2026/27, abierta GW1–3 | 0 → 0 | 0 |

**196/199 deadlines** tienen ahora un snapshot corroborado. Esto incluye las
38 jornadas de cada temporada 2021/22–2025/26; no implica cobertura temporal de las
doce temporadas del GT. Los tres huecos restantes pertenecen a la temporada
abierta. La ausencia de eventos en las horas consultadas no prueba no publicación.

`publication_selection` conserva los 164 testigos anteriores, valida los nuevos
contra su plan y sus eventos originales, y emite una selección diferente. Cada
captura sustituida es entre **4,02 y 35,93 horas más antigua**, según su reloj
declarado, que la de G20. Los nuevos pushes ocurrieron entre **6,65 y 39,38 horas**
antes del deadline. Esta distancia debe conservarse como frescura de la señal;
no se presentan los valores como si fueran los de la última captura.

Con esa selección, `bootstrap_state` genera un paquete separado que conserva
**143.720 filas de jugadores y 320 de managers**, cero rechazos y las mismas
claves. Hay **141.853 filas de jugadores** con publicación corroborada y 1.867 de
la temporada abierta sin testigo; los 320 managers están corroborados. G19 sigue
preservado. La auditoría verifica igualdad completa de las 119.382 filas de
snapshots conservados y compara 24.658 filas de snapshots sustituidos. Cambian
3.064 ownership, 152 precios, 174 estados, 212 probabilidades de jugar la próxima
jornada y 57 fechas de noticias. No se trasplantan valores posteriores.

```bash
python -m experiments.data_ground_truth.publication_alternatives \
  --raw-root "$BOOTSTRAP_RAW_ROOT" --provenance-root "$BOOTSTRAP_TIME_ROOT" \
  --archive-root "$PUBLICATION_ARCHIVE_ROOT" --out "$PUBLICATION_ALTERNATIVES_ROOT"
python -m experiments.data_ground_truth.publication_selection \
  --alternatives-root "$PUBLICATION_ALTERNATIVES_ROOT" \
  --original-archive-root "$PUBLICATION_ARCHIVE_ROOT" \
  --original-audit-root "$BOOTSTRAP_AUDIT_ROOT" --out "$PUBLICATION_SELECTION_ROOT"
python -m experiments.data_ground_truth.bootstrap_state \
  --root "$BOOTSTRAP_RAW_ROOT" --audit-root "$PUBLICATION_SELECTION_ROOT" \
  --package "$LABELS_V5_PACKAGE" --aliases-root "$BOOTSTRAP_ALIASES_ROOT" \
  --out "$BOOTSTRAP_SELECTED_STATE_ROOT"
python -m experiments.data_ground_truth.publication_state_audit \
  --selection-root "$PUBLICATION_SELECTION_ROOT" --state-root "$BOOTSTRAP_SELECTED_STATE_ROOT" \
  --previous-state-root "$BOOTSTRAP_STATE_V2_ROOT" --out "$PUBLICATION_STATE_AUDIT_ROOT"
```

[results-g21.json](results-g21.json) conserva métricas, hashes, error de adquisición
y cambios de campos. Selección y auditoría reproducen sus reportes byte por byte.
Suite local: 1.457 passed, 1 skipped, 79 deselected. La disponibilidad probada
permanece en testigos separados; los estados mantienen entrenamiento y admisión
predeadline deshabilitados. No hay cambios en GT v5 ni producción. Faltan el
contrato de admisión y replay, reglas/calendarios históricos, flags desconocidos,
los 78 kickoffs discrepantes y el universo elegible antiguo. Para 2026/27 conviene
contrastar la evidencia propia del collector antes de ampliar búsquedas externas.

## Gate G22: reglas y calendario de jornadas observados

`bootstrap_rules` extrae los 199 snapshots seleccionados en G21; 196 tienen
publicación corroborada. Conserva las secciones originales `game_settings`,
`game_config`, `chips` y `element_types` en objetos con hash, distinguiendo ausencia
real de una sección vacía o nula. No rellena reglas antiguas con las actuales.
Una proyección estratégica separa restricciones de plantilla de los conteos
variables de jugadores. El calendario exporta campos explícitos de jornada y
excluye resultados agregados y IDs de entradas ganadoras.

Se recuperan **7.562 observaciones de calendario de jornada** y **141 cambios de
deadline** entre snapshots seleccionados. Son cambios observados entre capturas,
no fechas exactas del anuncio. **Ninguno contiene fixtures**: saber los deadlines
no reconstruye qué equipos jugaban, dobles jornadas, aplazamientos o kickoffs
conocidos en esa fecha. Ese histórico continúa siendo una brecha específica.

| Temporada | Snapshots | Con chips y scoring explícitos | Con fixtures |
| --- | ---: | ---: | ---: |
| 2020/21, parcial | 6 | 0 | 0 |
| 2021/22 | 38 | 0 | 0 |
| 2022/23 | 38 | 0 | 0 |
| 2023/24 | 38 | 0 | 0 |
| 2024/25 | 38 | 23, desde GW16 | 0 |
| 2025/26 | 38 | 38 | 0 |
| 2026/27, abierta | 3 | 3, sin testigo temporal | 0 |

Los campos compartidos de `game_settings` y `game_config.rules` coinciden en los
snapshots que contienen ambas secciones. Esto no valida toda la semántica del
juego. `transfers_cap` no debe convertirse en capacidad de acumular transferencias
gratuitas; los campos, límites y excepciones requieren contratos diferenciados.
Las variantes de estructura también pueden reflejar la aparición de campos,
sin demostrar un cambio efectivo de reglas.

Se conservaron treinta observaciones de overrides no vacíos: dieciséis del
Assistant Manager en 2024/25 y catorce de Free Hit en 2025/26. En estas últimas,
GW1–14, la configuración del chip de la segunda mitad contiene
`rules.squad_squadsize=16`; el override desaparece desde la captura de GW15.
El dato queda pendiente de interpretación y no se aplica al simulador ni se
corrige automáticamente. Publicación probada no equivale a regla ejecutable válida.

Como contraste editorial, se adquirieron dos páginas oficiales con URL, hash y
fecha de descarga. [Los cambios de 2025/26](https://www.premierleague.com/en/news/4362211/all-you-need-to-know-about-changes-to-fantasy-for-202526)
describen ocho chips, ausencia de Assistant Manager y la recarga excepcional de
transferencias de GW16. [La explicación de los chips](https://www.premierleague.com/en/news/4362027)
explicita su caducidad por mitad de temporada y que Free Hit no puede jugarse en
GW19 y GW20 consecutivamente. Son referencias recuperadas ahora: la fecha editorial
no se transforma en un testigo histórico de publicación del contenido actual.

```bash
python -m experiments.data_ground_truth.bootstrap_rules \
  --raw-root "$BOOTSTRAP_RAW_ROOT" --selection-root "$PUBLICATION_SELECTION_ROOT" \
  --out "$BOOTSTRAP_RULES_ROOT"
```

[results-g22.json](results-g22.json) conserva cobertura, referencias y hashes.
Reporte reproducido byte por byte; 1.458 passed, 1 skipped, 79 deselected. Los
objetos y calendarios quedan fuera de Git, asociados al hash del snapshot y al
testigo G21 cuando existe. No se activa entrenamiento, replay ni producción.
La prioridad siguiente es adquirir calendarios históricos de fixtures y cerrar
la interpretación de reglas por temporada antes de comparar políticas de chips.

## Gate G23: versiones históricas de fixtures desde Git

Se inspeccionó el historial completo alcanzable del commit fijado
`9779cdbc0c07f6c900c2d0c181ddf6bb9c800f88` de
`vaastav/Fantasy-Premier-League`: clon no shallow, 531 commits alcanzables y nueve
rutas de datos de fixtures. Buscar todas las rutas históricas que contienen
`fixtures` no reveló rutas adicionales. El export conserva hashes y fechas de
committer/autor, sin nombres ni correos. Esto describe el historial alcanzable de
ese pin; no garantiza que nunca hayan existido otras ramas o historia reescrita.

`fixture_history` adquirió **254 versiones distintas**, 86.020.330 bytes, cero
errores. Cada archivo coincide con el SHA-1 del blob Git y queda guardado además
por SHA-256. Se preservan las versiones por commit, sin sustituirlas por el estado
final de temporada. Su fecha Git sigue siendo una declaración de fuente;
`available_at` permanece desconocido y la admisión predeadline está desactivada.

`fixture_history_audit` normaliza IDs, jornadas, kickoffs, flags y dificultades.
Conserva jornadas/horarios sin asignar y booleanos desconocidos; excluye los
resultados y estadísticas de partido de esta proyección de calendario. Rechaza
CSV ambiguos, IDs repetidos, pares home/away repetidos, partidos de un equipo
contra sí mismo y fechas sin zona horaria. Las 254 versiones pasaron y contienen
380 partidos cada una: **96.520 filas de versión de fixture**, no partidos nuevos.

Se observaron **2.020 transiciones de kickoff** y **387 de jornada asignada** entre
versiones consecutivas. Un mismo partido puede cambiar varias veces. No hubo
cambios observados de código, equipos o población de fixtures al comparar por ID
dentro de temporada. Esto no autoriza unir IDs de temporadas distintas.

| Temporada | Versiones adquiridas | Deadlines comparados | Commit previo ≤48h | Commit previo ≤7 días |
| --- | ---: | ---: | ---: | ---: |
| 2018/19 | 1, con commit posterior a temporada | — | — | — |
| 2019/20 | 45 | — | — | — |
| 2020/21 | 40 | 6 | 4 | 5 |
| 2021/22 | 40 | 38 | 19 | 34 |
| 2022/23 | 38 | 38 | 20 | 34 |
| 2023/24 | 38 | 38 | 21 | 32 |
| 2024/25 | 37 | 38 | 20 | 32 |
| 2025/26 | 12 | 38 | 6 | 11 |
| 2026/27, abierta | 3 | 3 | 2 | 2 |

La comparación utiliza los 199 deadlines de G21. Todos tienen una versión con
commit anterior, pero solo 92 están dentro de 48 horas y 150 dentro de siete días.
Son medidas **nominales**, no disponibilidad comprobada. En 2025/26 la antigüedad
máxima es 2.197,30 horas (unos 92 días): tener los 380 partidos no demuestra un
calendario suficientemente actualizado. Es prioritario complementar esa temporada.
2018/19 y 2019/20 no están representadas por los deadlines G21; el guion no
significa cobertura cero ni comparación realizada.

```bash
# En el clon completo del repositorio fuente fijado:
git log --format='commit%x09%H%x09%cI%x09%aI' --raw --no-abbrev --no-renames \
  9779cdbc0c07f6c900c2d0c181ddf6bb9c800f88 -- 'data/*/fixtures.csv' > "$FIXTURE_GIT_LOG"
python -m experiments.data_ground_truth.fixture_history \
  --log "$FIXTURE_GIT_LOG" --out "$FIXTURE_HISTORY_ROOT"
python -m experiments.data_ground_truth.fixture_history_audit \
  --root "$FIXTURE_HISTORY_ROOT" --selection-root "$PUBLICATION_SELECTION_ROOT" \
  --out "$FIXTURE_HISTORY_AUDIT_ROOT"
```

[results-g23.json](results-g23.json) conserva cobertura, hashes y límites. El
manifiesto raw contiene los 254 registros y las tablas normalizadas permanecen
fuera de Git. Auditoría reproducida byte por byte; 1.460 passed, 1 skipped,
79 deselected. No se habilita entrenamiento ni se modifica GT v5 o producción.
Faltan testigos externos de publicación de estos commits y una fuente más densa
para 2025/26, además de las brechas de reglas y etiquetas ya documentadas.

## Gate G24: fuentes complementarias y calendarios coherentes por commit

Se contrastó el historial Git fijado de otras tres fuentes. El mirror conserva
28 versiones desde abril de 2026; el archivo deportivo inspeccionado solo tiene
dos versiones de fixtures 2025/26 con commits de junio, posteriores a temporada.
FPL Core sí conserva un historial extenso de archivos por jornada. Se adquiere
la carpeta Premier League y se excluye la copia `By Gameweek`, que también puede
contener otros torneos. Los pins y hashes están en [results-g24.json](results-g24.json).

| Fuente | Archivos versionados adquiridos | Objetos distintos | Bytes asociados |
| --- | ---: | ---: | ---: |
| FPL Core, fixtures y matches por jornada | 5.019 | 2.312 | 27.102.963 |
| TopMarxFPL mirror, CSV de temporada | 28 | 28 | 968.298 |

La adquisición terminó sin errores y verificó cada blob Git. Los 79 borrados
observados de archivos Core se preservan en el manifiesto; no se borran los raw
adquiridos. La abundancia de archivos no equivale a calendarios completos ni a
nuevas temporadas de etiquetas.

`fixture_commit_plan` elige nominalmente un commit anterior a cada deadline de
2025/26, comprueba que pertenece al historial alcanzable del pin y exporta su árbol
completo. Evita construir una supuesta captura mezclando las últimas versiones de
archivos de commits distintos. Core tiene 38 árboles candidatos (38 o 76 archivos),
26 con commit a menos de 48 horas y antigüedad máxima de 194,56 horas. El mirror
solo tiene seis, GW33–38; tres están dentro de 48 horas. Estas cifras describen
fechas Git, no disponibilidad pública probada ni hora de captura del calendario.

`fixture_tree_audit` combina únicamente componentes del mismo árbol por ID del
proveedor. Conserva rutas, campos vacíos y valores originales. Solo combina valores
no nulos compatibles; discrepancias no se resuelven por preferencia de archivo.
IDs de proveedor y jornadas de proveedor no se equiparan automáticamente con FPL.
Tampoco se confunden IDs FPL de equipos con códigos Opta si falta una columna.

La auditoría encontró límites materiales:

- Core usa muchos `fixtures.csv` como plantillas sin kickoff. `matches.csv`
  incorpora fechas, pero numerosas observaciones carecen de zona horaria. Se
  conservan sus strings originales y se dejan sin timestamp normalizado; no se
  inventa UTC. En los 38 árboles hay 7.692 observaciones de fixture con ese límite.
- Tres árboles, GW13–15, tienen 370 IDs de partido en vez de 380. Hay treinta
  observaciones con asignaciones de jornada incompatibles entre componentes.
  Se registran los conflictos y no se completan los diez partidos con otro commit.
- Hay **749 observaciones de fechas raw para jornadas actuales o posteriores**,
  concentradas en GW26–33, pendientes de validar su reloj. En la proyección con
  zona acreditada hay **cero horarios futuros utilizables** de Core. No se declara
  que todos los valores raw estén vacíos ni que la fuente cierre esa brecha.
- El mirror aporta seis calendarios de 380 partidos, sin conflictos observados,
  con **209 observaciones de horarios futuros con zona explícita**. Son
  observaciones repetidas entre capturas, no 209 partidos adicionales. Su
  publicación histórica todavía requiere testigos externos.

```bash
# Exportar el historial desde cada clon fijado; para Core incluir ambos tipos:
git log --format='commit%x09%H%x09%cI%x09%aI' --raw --no-abbrev --no-renames \
  ce03f31b4032f3f89a1aa460ddc8a709ddeb56b6 -- 'data/*/matches.csv' 'data/*/fixtures.csv' \
  > "$CORE_FIXTURE_GIT_LOG"
python -m experiments.data_ground_truth.fixture_complement --source core \
  --log "$CORE_FIXTURE_GIT_LOG" --out "$CORE_FIXTURE_HISTORY_ROOT"
python -m experiments.data_ground_truth.fixture_commit_plan --source core \
  --repo "$CORE_SOURCE_GIT" --log "$CORE_FIXTURE_GIT_LOG" \
  --selection-root "$PUBLICATION_SELECTION_ROOT" --out "$CORE_FIXTURE_PLAN_ROOT"
python -m experiments.data_ground_truth.fixture_tree_audit \
  --root "$CORE_FIXTURE_HISTORY_ROOT" --plan-root "$CORE_FIXTURE_PLAN_ROOT" \
  --out "$CORE_FIXTURE_TREE_AUDIT_ROOT"
```

Para mirror usar `--source mirror`, el clon/pin y el export de su historial de
`data/2025/csv/fixtures.csv`. Ambos reportes de auditoría se reprodujeron byte por
byte. Suite: 1.463 passed, 1 skipped, 79 deselected; hashes de implementación
verificados. El parser conserva los límites de campos sin descartar el archivo
entero por una fecha sin zona. Cero errores de parseo no significa cero conflictos
ni calendario completo.

GT v5, estados anteriores, entrenamiento y producción permanecen intactos.
Sigue siendo necesario corroborar el reloj de Core, resolver identidad/jornada
del proveedor, obtener testigos de publicación y complementar el calendario de
la primera parte de 2025/26. La evidencia negativa de esta auditoría evita tratar
un repositorio muy activo como un calendario futuro completo.

## Gate G25: reloj del exportador e identidad de competición

Se adquieren y verifican por SHA-256 y blob Git **81 versiones del exportador**
Core; el historial también contiene un borrado. Cinco versiones no son Python
parseable y se conservan como evidencia desconocida. El código descargado se
inspecciona mediante AST, nunca se ejecuta. Los 38 árboles seleccionados tienen
un exportador adquirido.

Desde el commit `2c00c3886c421d488ff017d83e96631474b80847`
(9 de febrero de 2026), `infer_gameweek` usa `to_datetime(..., utc=True)`.
Es una hipótesis del consumidor para inferir jornadas; no demuestra la zona del
productor ni convierte por sí misma la columna exportada. El exportador lee una
tabla externa `matches`; no se accede a esa base de terceros.

El diagnóstico cruza pares de códigos de equipo con el calendario final FPL,
únicamente cuando ambas fechas comparadas son anteriores al commit de origen.
No usa ese calendario final como entrada predeadline. Hay **6.552 comparaciones**,
**6.233 coincidencias bajo UTC** y **319 discrepancias**, correspondientes a
71 IDs del proveedor. Las observaciones se repiten entre capturas: no son ensayos
independientes ni una medida de calidad predictiva. El enlace por equipos es
solo candidato: no acredita identidad de partido entre competiciones.

Dos ejemplos muestran por qué no basta corregir la zona horaria:

| Registro bajo Premier League | Fecha raw Core | Fecha de liga en referencia | Evidencia editorial |
| --- | --- | --- | --- |
| Brentford–Aston Villa, observado en árbol GW5 | 2025-09-16 19:00 sin zona | 2025-08-23 14:00 UTC | [Brentford anuncia Carabao Cup el 16 de septiembre, 20:00 BST](https://www.brentfordfc.com/en/news/article/first-team-carabao-cup-round-three-brentford-v-aston-villa) |
| Wolves–Everton, observado en árbol GW6 | 2025-09-23 18:45 sin zona | 2025-08-30 14:00 UTC | [Wolves anuncia Carabao Cup el 23 de septiembre, 19:45 local](https://www.wolves.co.uk/news/mens-first-team/20250903-new-september-fixture-dates/) |

Las fechas coinciden con encuentros de copa, pese a la carpeta y slug de liga.
Esto indica contaminación de identidad/fecha en esos registros; no prueba el
mecanismo que la produjo ni que todas las discrepancias tengan la misma causa.
Ambas páginas oficiales se archivaron con hash y fecha de descarga actual; no
constituyen testigos de publicación histórica del repositorio.

```bash
python -m experiments.data_ground_truth.core_clock_evidence \
  --repo "$CORE_SOURCE_GIT" --export-log "$CORE_EXPORTER_GIT_LOG" \
  --code-root "$CORE_CLOCK_SOURCE_ROOT" --tree-root "$CORE_FIXTURE_TREE_AUDIT_ROOT" \
  --fixture-root "$FIXTURE_HISTORY_AUDIT_ROOT" --teams-root "$RAW_HISTORY_V2_ROOT" \
  --out "$CORE_CLOCK_EVIDENCE_ROOT"
```

El log se exporta con el mismo formato de G24, fijado a su pin, para
`scripts/export_data.py`. Los cuatro artefactos del diagnóstico se reprodujeron
byte por byte. Las pruebas verifican inspección sin ejecución, fuentes inválidas,
exclusión de fechas futuras y tratamiento estacional del reloj británico.
Hashes, revisiones, ejemplos y referencias: [results-g25.json](results-g25.json).

El gate no normaliza las 749 fechas futuras raw, no admite fixtures al replay y
no modifica GT v5 ni producción. La siguiente prioridad es acreditar competición,
ID de evento y calendario publicado antes del deadline, además del reloj; más
archivos de esta fuente por sí solos no cierran la brecha.

## Gate G26: horario previsto y actualización del día de partido

`kickoff_semantics` verifica GT v5 y contrasta **207.363 filas de ocho temporadas**
(2018/19–2025/26) con la última versión fijada de fixtures de cada temporada.
No faltan referencias ni relojes en ese cruce; no hay diferencias de jornada.
Las cuatro temporadas anteriores no tienen historial en esta fuente y quedan
explícitamente fuera de esta verificación, no declaradas correctas por ausencia.

Las **78 diferencias** son del mismo fixture 263 de 2021/22, Brighton–Aston Villa,
código 2210533. GT conserva `2022-02-26T15:00:00Z`; la referencia final e historiales
individuales conservan 15:30. El historial de fixtures mantiene ID, código y equipos:
la primera versión adquirida usa 15:00; la primera versión adquirida con 15:30
tiene commit del 12 de marzo de 2022. Esa fecha de commit no es la fecha real del
anuncio ni prueba de publicación.

La [crónica local del día](https://www.brightonandhovenews.org/2022/02/26/traffic-delays-kick-off-as-brighton-and-hove-albion-prepare-to-host-aston-villa/)
explica el retraso hasta 15:30 por tráfico. Se archiva el HTML con hash y fecha de
descarga actual. La noticia corrobora la explicación, pero no acredita el instante
en que FPL actualizó su API. Hay un cambio real de horario: no corresponde aplicar
una corrección global de zona ni tratar las 78 filas como 78 errores independientes.

El contrato actual de `event_time_utc` copia el kickoff del CSV de etiquetas; no
garantiza inicio real observado ni publicación de resultados. Se preserva GT v5
y se añade la trayectoria del fixture como evidencia separada. Un futuro paquete
con relojes explícitos deberá distinguir horario previsto observado, horario
actualizado y disponibilidad de cada observación; no retropropagar 15:30 a un
estado anterior al anuncio. Ninguno de estos timestamps acredita por sí solo
cuándo las etiquetas estuvieron disponibles.

```bash
python -m experiments.data_ground_truth.kickoff_semantics \
  --package "$GT_V5_PACKAGE" --fixture-root "$FIXTURE_HISTORY_AUDIT_ROOT" \
  --out "$KICKOFF_SEMANTICS_ROOT"
```

Reporte y dos sidecars reproducidos byte por byte. Suite: **1.468 passed,
1 skipped, 79 deselected**. Las pruebas cubren horarios equivalentes con offsets,
referencias ausentes, valores desconocidos, identidades duplicadas y preservación
de entradas. [Resultados y hashes G26](results-g26.json). Este gate explica la
discrepancia conocida y amplía su contraste al resto de temporadas disponibles;
no añade temporadas ni habilita entrenamiento o replay.

## Gate G27: nueva serie histórica de fixtures

El descubrimiento inspeccionó ocho repositorios públicos con árboles fijados,
ninguno truncado. `Schwetche/fpl_project` contiene una serie de `data/fixtures.csv`
y snapshots derivados. Se fijó el commit
`34f681c7b756ae901982e53cdcb6cd061dbd0482`, con 2.292 commits alcanzables en clon
no shallow. Los scripts inspeccionados leen el endpoint oficial FPL de fixtures;
no se ejecuta código descargado. Los pins y hashes de descubrimiento están en
[results-g27.json](results-g27.json).

Se adquieren **199 versiones, 155 objetos distintos y 79.817.488 bytes asociados**,
sin errores de descarga. Cada objeto se verifica por SHA-256 y blob Git. Se
incluye la serie principal, snapshots de fixtures y un JSON raw; no se adquieren
cuentas, ligas privadas ni archivos ajenos a esta selección.

La auditoría interpreta 193 versiones y registra seis errores de schema en
snapshots derivados. Para acreditar temporada exige los 380 partidos con la
misma tupla `(id, code, team_h, team_a)` que la referencia FPL fijada. La serie
principal contiene 132 versiones de 2025/26, trece de 2026/27 y dos sin `code`:
estas últimas se conservan sin identidad acreditada. Los snapshots derivados
no participan en la selección por deadline. No se trasladan scores ni estadísticas
a la proyección de calendario.

Para 2025/26 hay versión de la serie principal con commit nominal anterior en
**36/38 deadlines**, GW3–38; **15/38** con antigüedad de hasta 48 horas. Se observan
6.647 fechas futuras en esos calendarios, repetidas entre capturas. La unión con
Vaastav amplía de **6 a 18 deadlines** con versión previa de hasta 48 horas:
doce ventanas adicionales, detalladas en resultados. Esto mide fechas Git, no
hora de captura, publicación probada ni integridad de todas las actualizaciones
intermedias. La fuente no añade una nueva temporada completa de etiquetas.

```bash
git log --format='commit%x09%H%x09%cI%x09%aI' --raw --no-abbrev --no-renames \
  34f681c7b756ae901982e53cdcb6cd061dbd0482 -- 'data/*fixtures*' 'data/raw/*/fixtures.json' \
  > "$ADDITIONAL_FIXTURE_GIT_LOG"
python -m experiments.data_ground_truth.additional_fixture_history \
  --log "$ADDITIONAL_FIXTURE_GIT_LOG" --out "$ADDITIONAL_FIXTURE_RAW_ROOT"
python -m experiments.data_ground_truth.additional_fixture_audit \
  --root "$ADDITIONAL_FIXTURE_RAW_ROOT" --reference-root "$FIXTURE_HISTORY_AUDIT_ROOT" \
  --selection-root "$PUBLICATION_SELECTION_ROOT" --out "$ADDITIONAL_FIXTURE_AUDIT_ROOT"
```

El comando Git se ejecuta dentro del clon de la fuente. Reporte, sidecars y
objetos normalizados se reprodujeron byte por byte. Suite: **1.470 passed,
1 skipped, 79 deselected**. Se prueban identidad completa, códigos ausentes,
cambios de equipos, clocks desconocidos y exclusión de resultados. GT v5,
entrenamiento y producción intactos. Próximo gate: testigos de publicación y
comparación de frescura conjunta; los 36 candidatos no se admiten aún al replay.

## Gate G28: publicación histórica de calendarios corroborada

`fixture_publication` liga cada uno de los 36 candidatos de G27 con su CSV raw,
blob Git, commit alcanzable del pin y objeto normalizado. Verifica el reloj real
del commit contra los metadatos adquiridos. Después busca eventos públicos de
`Schwetche/fpl_project`, ID GitHub `1042951725`, en [GH Archive](https://www.gharchive.org/).
Se preservan solo eventos del repositorio exacto, con hash del archivo horario
y de la línea original; no se retiene actividad GitHub ajena.

La primera pasada adquirió 36 horas y encontró 24 coincidencias directas. Para
los doce casos sin coincidencia se adquirió también la hora siguiente: en total
**48 horas, 1.971.757.699 bytes y cero errores**. Los eventos cuyo head no coincide
se contrastan mediante `git merge-base --is-ancestor`: solo un commit realmente
alcanzable desde el head público puede recibir ese testigo. El sentido inverso
no constituye evidencia. Los campos proyectados del evento se vuelven a validar
contra su línea raw sellada antes de utilizarlos.

Resultado: **26/36 candidatos con publicación previa corroborada** —24 exactos y
dos por ascendencia, GW23 y GW37—. Cubren **5.015 observaciones futuras de fixtures**,
repetidas entre calendarios; trece tienen commit nominal de hasta 48 horas antes
del deadline. La hora del push es una cota superior conservadora de publicación,
no la hora de captura de la API. La antigüedad máxima de publicación entre los
seleccionados ronda 200 horas: evidencia temporal no equivale a máxima frescura.

Quedan sin testigo en las horas examinadas GW9,13,17,18,25,26,27,28,31,32;
GW1–2 no tenían candidato G27. Un evento ausente no prueba no publicación ni
justifica reemplazar el calendario por su versión final. La siguiente búsqueda
puede usar capturas anteriores y fuentes complementarias, midiendo su antigüedad.

```bash
python -m experiments.data_ground_truth.fixture_publication \
  --root "$FIXTURE_PUBLICATION_ROOT" --audit-root "$ADDITIONAL_FIXTURE_AUDIT_ROOT" \
  --raw-root "$ADDITIONAL_FIXTURE_RAW_ROOT" --repo "$ADDITIONAL_FIXTURE_SOURCE_GIT"
```

El reporte y testigos se reprodujeron byte por byte desde los eventos archivados,
volviendo a validar sus hashes, proyecciones y ascendencia. Suite: **1.473 passed,
1 skipped, 79 deselected**; pruebas de repositorio exacto, privacidad, límites de
deadline, alteración de evidencia y ascendencia sobre un grafo Git local real.
[Resultados G28](results-g28.json) conserva hashes y los dos testigos indirectos.
Los flags de admisión del paquete G27 no se reescriben: los testigos son evidencia
separada y no habilitan entrenamiento, replay completo ni cambios en producción.

## Gate G29: calendarios anteriores con publicación probada

Para las diez ventanas G28 sin testigo, se planificaron 48 versiones anteriores
de la serie principal, con identidad FPL acreditada y antigüedad nominal máxima
de catorce días. La búsqueda intenta primero la más reciente y se detiene por
jornada al hallar un testigo válido; no usa métricas de resultado para elegir.
Cada intento vuelve a verificar raw, blob, ascendencia del pin y reloj Git.

Se evaluaron **13 candidatos en dos rondas**, adquiriendo **26 horas de GH Archive,
1.043.275.936 bytes**, sin errores. Se recuperaron **las diez ventanas**. Las
sustituciones son entre 23,65 y 143,99 horas más antiguas que el candidato original,
y tienen entre 36,57 y 199,51 horas de antigüedad al deadline. La cota de catorce
días limita la búsqueda; no constituye una garantía de frescura suficiente para
cualquier política de decisión.

El selector revalida también los 26 testigos G28 contra sus eventos raw y grafo
Git. Emite `selected_calendars.json`, ligado por hash a los objetos normalizados
G27, con **36 calendarios, GW3–38 de 2025/26**, y evidencia de publicación previa
para cada uno. Hay **6.648 observaciones futuras** repetidas entre capturas,
catorce calendarios con commit previo de hasta 48 horas y antigüedad nominal
máxima de 199,74 horas. GW1–2 siguen pendientes de fuente/testigo complementario.

Comparadas con las versiones más recientes sin testigo, cuatro sustituciones
presentan cambios: **32 campos kickoff y cuatro campos jornada**, en 32
observaciones de fixture. El archivo de diferencias conserva ambos valores.
Es un diagnóstico retrospectivo: no rellena la captura anterior con valores
posteriores ni declara equivalente un calendario más antiguo. GT v5 y los
snapshots de estados permanecen intactos.

```bash
python -m experiments.data_ground_truth.fixture_publication_alternatives \
  --publication-root "$FIXTURE_PUBLICATION_ROOT" --audit-root "$ADDITIONAL_FIXTURE_AUDIT_ROOT" \
  --raw-root "$ADDITIONAL_FIXTURE_RAW_ROOT" --repo "$ADDITIONAL_FIXTURE_SOURCE_GIT" \
  --out "$FIXTURE_PUBLICATION_ALTERNATIVES_ROOT"
```

Reporte, plan, intentos, sustituciones y selección consolidados se reprodujeron
byte por byte. Suite: **1.475 passed, 1 skipped, 79 deselected**; se prueban límites
de antigüedad, exclusión de futuro, temporada incorrecta, identidad desconocida y
snapshots derivados. [Resultados G29](results-g29.json). Los testigos acreditan
publicación, no captura API ni readiness de replay completo; entrenamiento y
producción continúan sin cambios.

## Gate G30: publicación histórica y selección conjunta de calendarios

La auditoría de la fuente Vaastav examina los 199 candidatos G23. Adquiere
241 horas de GH Archive (22.582.820.815 bytes comprimidos procesados) y acredita
149 candidatos mediante PushEvent. Dos horas, 2021-10-25-09 y -10, devuelven 404;
se conservan como fallos, también durante la reproducción offline.

Una segunda extracción busca PullRequestEvent públicos, cerrados y fusionados,
con repositorio base exacto y commit de merge verificado. Procesa 40 horas
(3.252.130.682 bytes), parcialmente solapadas con la extracción de pushes: esos
bytes no representan un total de archivos únicos adicionales. Recupera dos
testigos y eleva esta fuente a **151/199 candidatos**. En GW2 2025/26 el commit
exacto aparece en un merge público del 20 de agosto; buscar únicamente pushes
había dejado sin acreditar esa ventana. Se usa la hora del evento como cota
superior conservadora, nunca se retrocede a la hora declarada del commit.

El selector conjunto vuelve a verificar los 151 testigos y los 36 calendarios
G29, incluidos hashes raw/normalizados, identidad, reloj y ascendencia Git.
Selecciona por jornada un calendario completo con el commit más reciente entre
los acreditados, sin usar resultados deportivos ni mezclar sus filas.

| Temporada | Deadlines acreditados | Commit de hasta 48 h |
| --- | ---: | ---: |
| 2020/21, tramo GW33–38 | 6/6 | 4 |
| 2021/22 | 34/38 | 18 |
| 2022/23 | 36/38 | 19 |
| 2023/24 | 36/38 | 20 |
| 2024/25 | 34/38 | 17 |
| 2025/26 | 38/38 | 14 |
| 2026/27, tramo GW1–3 | 0/3 | 0 |

Resultado: **184/199 deadlines**, con **7.398 observaciones futuras de fixtures**
en los 38 calendarios 2025/26 (repetidas entre snapshots). La antigüedad nominal
máxima de esa temporada es 344,67 horas, correspondiente a GW1. La publicación
acreditada no garantiza que la fuente haya capturado todos los cambios recientes.
Quedan doce ventanas de temporadas cerradas y tres de la temporada abierta.

```bash
python -m experiments.data_ground_truth.historical_fixture_publication \
  --root "$HISTORICAL_PUBLICATION_ROOT" --audit-root "$FIXTURE_AUDIT_ROOT" \
  --raw-root "$FIXTURE_RAW_ROOT" --repo "$FIXTURE_SOURCE_GIT" \
  --extended-candidate 2025-26:2 --offline
python -m experiments.data_ground_truth.historical_pr_publication \
  --publication-root "$HISTORICAL_PUBLICATION_ROOT" --audit-root "$FIXTURE_AUDIT_ROOT" \
  --raw-root "$FIXTURE_RAW_ROOT" --repo "$FIXTURE_SOURCE_GIT" \
  --out "$HISTORICAL_MERGE_PUBLICATION_ROOT" --offline
python -m experiments.data_ground_truth.calendar_publication_selection \
  --base-root "$EXPERIMENTS_ROOT" --out "$CALENDAR_SELECTION_ROOT"
```

El selector fija las versiones de carpetas de entrada indicadas en su código y
reporte. Los dos primeros comandos requieren caché de horas/eventos y fallos
para modo offline; omitir `--offline` permite adquisición GET. El comando de
pushes conserva salida no cero por las dos horas ausentes: no implica que los
149 testigos válidos se hayan perdido.

Los tres reportes y sus índices se reprodujeron byte por byte desde la caché,
con hashes y evidencia revalidados. [Resultados G30](results-g30.json) conserva
cobertura, huecos, hashes y verificación. GT v5 y producción permanecen intactos;
no se habilita entrenamiento ni replay completo. El próximo gate de datos debe
medir frescura y cerrar ventanas, además de tipar y validar rendimiento acumulado
raw antes de usarlo como variables causales.

## Gate G31: rendimiento raw tipado y cambios de semántica

Se extraen 22 campos de rendimiento de los 199 snapshots seleccionados en G21,
verificando manifiesto, hashes y correspondencia de calendario. El paquete
conserva **143.720 filas de jugadores** y excluye 320 filas de managers. Cada
celda distingue ausencia, nulo, valor válido y motivo de rechazo. Conteos exigen
enteros no negativos; puntos y BPS admiten valores negativos; xG/xA usan decimales
finitos no negativos. No se rellenan ausencias con cero.

Los dominios numéricos pasan sin celdas inválidas, pero eso no demuestra semántica
homogénea. La comparación temporal detecta **31.071 descensos de celda**, de los
que **27.211 ocurren entre GW1 y GW2**. Antes de GW1 ya hay minutos positivos para
372 jugadores en 2021/22, 396 en 2022/23, 400 en 2023/24, 407 en 2024/25, 395 en
2025/26 y 400 en 2026/27. No se interpretan como minutos acumulados de la nueva
temporada, ni se restan automáticamente para reconstruir jornadas.

Los descensos restantes tampoco equivalen todos a errores: puntos y BPS pueden
bajar legítimamente. Hay descensos de xG/xA y componentes esperados en ventanas
posteriores de 2022/23 que requieren conciliación. `anomalies.json` conserva
valores, jornadas, código de origen y SHA del snapshot; no corrige ni elimina
observaciones. Las comparaciones se separan por temporada, elemento y código,
sin aplicar alias ni inferir identidad entre temporadas.

| Campo | Cobertura numérica válida |
| --- | --- |
| Minutos y puntos | Todas las 143.720 filas seleccionadas |
| Titularidades y xG/xA/xGC | Ausentes en 2020/21–2021/22; 16.897/26.198 filas de 2022/23; completas desde 2023/24 en esta selección |
| Contribuciones defensivas y sus nuevos componentes | Se informa cobertura por campo y temporada en resultados; no se fabrican datos históricos anteriores |

```bash
python -m experiments.data_ground_truth.bootstrap_performance \
  --raw-root "$BOOTSTRAP_RAW_ROOT" --selection-root "$PUBLICATION_SELECTION_ROOT" \
  --out "$PERFORMANCE_AUDIT_ROOT"
```

Reporte, filas comprimidas e incidencias se reproducen byte por byte.
[Resultados G31](results-g31.json) conserva hashes y cobertura detallada.
Esta auditoría tipa los valores raw; los testigos temporales G21 siguen separados
y no se revalidan aquí. `available_at` permanece nulo y entrenamiento deshabilitado.
La siguiente conciliación debe determinar el período representado por cada campo,
especialmente en pretemporada, antes de construir variables o deltas causales.
GT v5 y producción permanecen intactos.

## Gate G32: conciliación de estadísticas previas a GW1

Se contrastan **3.622 filas anteriores a GW1**, de 2021/22–2026/27, con los totales
GT v5 de la temporada inmediatamente anterior. La comparación utiliza el código
de origen, trece componentes enteros y particiones verificadas por hash. Una
coincidencia de código es una clave de contraste, no prueba independiente de
identidad personal; no aplica alias ni rellena los códigos ausentes.

| Temporada del snapshot | Todos los campos comparados iguales | Con diferencias | Sin código en referencia previa |
| --- | ---: | ---: | ---: |
| 2021/22 | 403 | 3 | 123 |
| 2022/23 | 427 | 0 | 131 |
| 2023/24 | 475 | 1 | 165 |
| 2024/25 | 475 | 2 | 133 |
| 2025/26 | 505 | 6 | 174 |
| 2026/27 | 454 | 7 | 138 |

En total, **2.739 de 2.758 filas con código coincidente** concuerdan en los
componentes comparados. Esto respalda el uso de estadísticas de la temporada
anterior como explicación de la discontinuidad GW1–GW2, sin autorizar un cambio
global de período para todos los campos. Los 864 códigos sin referencia siguen
sin conciliar: no se etiquetan automáticamente como jugadores nuevos.

Hay **19 excepciones**: diecisiete tienen cero en los campos discrepantes frente
a totales previos positivos; dos de 2026/27 presentan discrepancias no nulas.
El índice conserva ambos valores, código, elemento, temporada previa y SHA raw.
No se reescribe el snapshot ni GT v5, y no se asume que la referencia final sea
la información publicada antes del deadline. Un total con alguna fila nula se
conserva desconocido; códigos asociados a más de un elemento son ambiguos.

```bash
python -m experiments.data_ground_truth.preseason_performance \
  --performance-root "$PERFORMANCE_AUDIT_ROOT" --package "$GT_V5_ROOT" \
  --out "$PRESEASON_RECONCILIATION_ROOT"
```

Reporte e índice se reprodujeron byte por byte. Suite: **1.503 passed, 1 skipped,
79 deselected**. Se verifican aislamiento de temporadas, ausencia frente a cero,
códigos ambiguos, totales parciales y rechazo de truncamiento de decimales o
infinitos. [Resultados G32](results-g32.json) fija hashes y cobertura. La primera
corrida exploratoria tenía una selección cruzada entre temporadas y fue rechazada;
los resultados aceptados son `preseason-performance-v2`, reproducidos en `v3`.

El siguiente paso es conciliar las excepciones con snapshots y fuentes originales,
y definir el período por campo. Este es un diagnóstico retrospectivo: no incorpora
totales finales como variables predeadline ni habilita entrenamiento/producción.

## Gate G33: historia raw de las excepciones de pretemporada

Se rastrean las diecinueve excepciones G32 en **694 snapshots anteriores a GW1**
de sus respectivas temporadas. El proceso vuelve a verificar inventario, hashes,
calendario e identidad de elemento/código; no une códigos distintos. Produce
**2.433 observaciones jugador-snapshot**: 2.004 presentes y 429 ausentes.

**Ninguna excepción tiene una captura anterior que concuerde con todos los totales
previos comparados.** Ocho muestran una transición de ausencia a presencia;
las otras once están presentes con valores constantes en todo el tramo observado.
En las ocho altas tampoco cambian después los componentes examinados antes de GW1.
Esto descarta reemplazarlas con una versión anterior equivalente dentro de este
archivo, pero no explica por sí solo la causa ni prueba ausencia continua entre
capturas.

Ejemplos de primeras apariciones nominales de 2025/26: Ramsdale el 5 de agosto,
Ugochukwu el 7 y Broja/Hermansen el 11. Son horas declaradas por el archivo,
no prueba de publicación ni fecha exacta de incorporación al juego. La ausencia
no se convierte en rendimiento cero, y un evento editorial de transferencia no
certifica la semántica del campo FPL. Las diecinueve excepciones siguen preservadas,
sin rellenarse con el GT final.

```bash
python -m experiments.data_ground_truth.preseason_exception_history \
  --raw-root "$BOOTSTRAP_RAW_ROOT" --audit-root "$BOOTSTRAP_AUDIT_ROOT" \
  --reconciliation-root "$PRESEASON_RECONCILIATION_ROOT" \
  --out "$PRESEASON_EXCEPTION_HISTORY_ROOT"
```

Reporte y cronologías se reprodujeron byte por byte. Suite: **1.506 passed,
1 skipped, 79 deselected**. Pruebas distinguen ausencia, identidad incompatible,
ceros, nulos y coincidencias anteriores sin sobrescribir valores posteriores.
[Resultados G33](results-g33.json) contiene hashes y resúmenes por excepción.
No se habilita entrenamiento ni se modifica GT v5 o producción. Este gate cierra
la búsqueda de una captura anterior correctiva en el archivo examinado; siguen
pendientes fuentes independientes y los demás huecos de cobertura/frescura.

Como contexto editorial se archivó el [anuncio oficial de Ramsdale en Newcastle](https://www.newcastleunited.com/en/news/aaron-ramsdale-signs-for-newcastle-united).
La página de entrevista de Ugochukwu encontrada en búsqueda devolvió HTTP 404
en adquisición directa; se registra el fallo, sin atribuirle evidencia descargada.
Estas referencias no cambian los valores FPL ni acreditan publicación histórica.

## Gate G34: calendarios anteriores publicados para ventanas pendientes

Se reejecuta G30 y se exige reproducción exacta de reporte e índice, revalidando
raw, Git y testigos. Para ventanas pendientes se selecciona el calendario completo
más reciente de una jornada anterior de la misma temporada, con publicación
anterior al deadline y antigüedad nominal máxima de catorce días. La cota se
aplica solo a las adiciones; no redefine ni rejuvenece las 184 selecciones G30.
No se encadenan imputaciones ni se elige por resultados deportivos.

| Temporada / GW añadida | GW de origen | Antigüedad nominal, horas | Diferencias de horario posteriores |
| --- | ---: | ---: | ---: |
| 2021/22 GW10 | 9 | 264,92 | 2 |
| 2021/22 GW28 | 27 | 192,48 | 0 |
| 2022/23 GW14 | 12 | 289,58 | 22 |
| 2023/24 GW17 | 16 | 177,98 | 0 |
| 2023/24 GW37 | 36 | 193,43 | 0 |
| 2024/25 GW15 | 14 | 127,10 | 0 |
| 2024/25 GW27 | 26 | 116,98 | 0 |

La selección crece a **191/199 deadlines**. 2023/24 y 2025/26 alcanzan 38/38;
2021/22 y 2024/25 quedan en 36/38, 2022/23 en 37/38. El tramo 2020/21 conserva
6/6. No aumenta el conteo de calendarios con commit de hasta 48 horas: esto
amplía cobertura con evidencia anterior, no la frecuencia de captura.

Quedan ocho ventanas: 2021/22 GW31–32, 2022/23 GW23, 2024/25 GW1 y GW5,
y 2026/27 GW1–3. La comparación contra los candidatos posteriores sin testigo
registra **24 diferencias de kickoff**, todas futuras respecto al deadline, y
ninguna de jornada. Se preservan ambos valores en `deltas.json`; las versiones
posteriores no se incorporan a las entradas. Se valida identidad completa de
fixture antes de comparar. El testigo conserva su jornada/deadline de origen,
y la selección registra por separado el nuevo contexto de uso.

```bash
python -m experiments.data_ground_truth.calendar_carryforward \
  --base-root "$EXPERIMENTS_ROOT" --out "$CALENDAR_CARRYFORWARD_ROOT" \
  --max-age-hours 336
```

Reporte, selección y diferencias se reprodujeron byte por byte; el proceso
revalida también el padre en una carpeta separada. Suite: **1.509 passed,
1 skipped, 79 deselected**. Pruebas cubren límites de edad, publicación estricta,
aislamiento de temporada, identidad y conservación de valores anteriores.
[Resultados G34](results-g34.json). La cobertura no acredita frescura suficiente
para replay completo: GT v5, entrenamiento y producción continúan intactos.

## Gate G35: publicación ampliada y búsqueda por descendientes

La búsqueda de las ocho ventanas G34 pendientes se amplía desde la tercera hora
del commit hasta el offset 24, siempre antes del deadline. Retiene pushes y merges
públicos fusionados en una sola adquisición y se detiene por ventana acreditada.
Procesa **133 horas, 8.684.572.272 bytes comprimidos**, sin errores, y acredita
GW1 2024/25 mediante un push de las 19:58:48 UTC del 15 de agosto de 2024.
El commit del calendario es ancestro verificado del head públicamente observado.

Una segunda búsqueda utiliza relojes de commits descendientes para localizar
horas relevantes; el reloj Git orienta la consulta, pero no acredita publicación.
Examina **9 horas, 762.509.285 bytes**, sin errores, y corrobora GW1 y GW5 2024/25.
En GW5 el testigo es un push del 20 de septiembre de 2024 a las 12:24:19 UTC,
cuatro días después del commit del calendario y todavía antes del deadline.
Los archivos de ambas rutas se solapan en tres horas: la unión contiene
**139 horas únicas y 9.334.044.383 bytes comprimidos únicos**. Los eventos ajenos
al repositorio no se retienen; se conservan líneas raw relevantes y hashes del
archivo de origen. No se suman adquisiciones solapadas como datos nuevos únicos.

El integrador revalida el padre G34 y cada nuevo testigo contra raw y grafo Git,
y deduplica las jornadas coincidentes. Resultado: **193/199 deadlines**;
2023/24, 2024/25 y 2025/26 alcanzan 38/38. Las nuevas selecciones GW1/GW5 de
2024/25 tienen antigüedad nominal de 24,22 y 116,13 horas, respectivamente.
La cobertura total con commit de hasta 48 horas pasa de 92 a 93 calendarios.
Quedan 2021/22 GW31–32, 2022/23 GW23 y 2026/27 GW1–3. La ausencia de testigo
en las horas examinadas no demuestra que el calendario no se hubiera publicado.

```bash
python -m experiments.data_ground_truth.calendar_publication_extension \
  --base-root "$EXPERIMENTS_ROOT" --out "$CALENDAR_EXTENSION_ROOT" --max-offset 24
python -m experiments.data_ground_truth.calendar_descendant_publication \
  --base-root "$EXPERIMENTS_ROOT" --out "$CALENDAR_DESCENDANT_ROOT"
python -m experiments.data_ground_truth.calendar_extension_selection \
  --base-root "$EXPERIMENTS_ROOT" --extension-root "$CALENDAR_EXTENSION_ROOT" \
  --extension-root "$CALENDAR_DESCENDANT_ROOT" --out "$CALENDAR_EXTENSION_SELECTION_ROOT"
```

Las dos búsquedas admiten `--offline`. Reportes, testigos y selección conjunta se
reprodujeron byte por byte, con revalidación del padre y evidencia por objeto.
Suite: **1.513 passed, 1 skipped, 79 deselected**. Pruebas incluyen límite exclusivo
del deadline, merges sin push, reloj con zona, ascendencia y ausencia de red offline.
[Resultados G35](results-g35.json) fija hashes, cobertura y contabilidad de archivos.
GT v5, entrenamiento y producción permanecen intactos; la disponibilidad histórica
no garantiza frescura suficiente ni readiness de replay completo.

La exploración adicional de metadatos públicos actuales no encontró PRs asociados
a los siete commits candidatos distintos; esto solo orienta investigación, no
prueba no publicación. Para el siguiente gate se localizó otra fuente: el inventario
raw del collector propio contiene 55 manifiestos FPL, desde 2026-08-24 hasta
2026-09-06, con bootstrap y fixtures separados. El inventario no acredita todavía
hashes ni admisión temporal al paquete; la primera captura es posterior a GW1.
Se consultó en lectura, sin recoger perfiles autenticados ni modificar controles.

## Gate G36: archivos públicos del collector propio y cierre de ingesta

Se exportan en lectura **55 bundles FPL 2026/27**, desde el 24 de agosto hasta
el corte 2026-09-06T04:30:33.627Z. Los cuerpos exportados son exclusivamente
`bootstrap-static.json` y `fixtures.json`: **77 objetos únicos, 95.043.896 bytes**.
Se conservan aparte los 55 manifiestos originales como metadata de procedencia;
incluyen la referencia pública al equipo configurado, pero no se copian cuerpos
de perfiles, historia o picks. Esa metadata de operador no debe confundirse con
un dataset de jugadores preparado para distribución pública.

El exportador verifica tamaño y SHA contra cada manifiesto original; la extracción
local restringe nombres, tipos y tamaños de miembros y rechaza conflictos o
referencias fuera del inventario. La auditoría vuelve a comprobar la proyección
contra el manifiesto original sellado, evitando que una proyección alterada se
presente como si conservara el mismo hash de origen.

La consulta PostgreSQL usa `connect_readonly` y transacción `READ ONLY`. Se
recuperan 55 registros de ingesta y se enlazan inequívocamente por ruta, hash del
manifiesto y hash declarado del bundle. Todos están `completed`. El hash global
del bundle queda como referencia del ledger: no se recalcula sobre archivos de
cuenta que deliberadamente no se exportan.

**`observed_at` precede a las descargas; no es una cota superior de disponibilidad.**
La auditoría usa `finished_at` de la ingesta completada. El máximo intervalo entre
inicio de captura y cierre es 6,482326 segundos. Es evidencia del reloj y ledger
propios, distinta de un testigo externo de publicación; se conserva ese origen.

Se normalizan **34.512 estados de jugadores**, cero managers y **20.900 observaciones
de fixtures**. Las 55 capturas tienen 380 identidades de fixture coincidentes con
la referencia de temporada, 20 clubes, 38 jornadas y claves de jugador no ambiguas.
Se preservan las ausencias de campos de estado, sin introducir elegibilidad ni
admisión a entrenamiento por la sola presencia del registro.

| Ventana | Jugadores | Inicio de captura UTC | Ingesta completada UTC |
| --- | ---: | --- | --- |
| 2026/27 GW2 | 620 | 2026-08-28 15:06:59.164 | 2026-08-28 15:07:00.355049 |
| 2026/27 GW3 | 652 | 2026-09-04 15:30:13.423 | 2026-09-04 15:30:15.894142 |

Ambas ingestas terminan antes de su deadline: aproximadamente 2,383 y 1,996 horas,
respectivamente. El calendario del snapshot debe coincidir con el deadline de
referencia. GW1 no tiene captura previa en este inventario. Los dos candidatos
se entregan en `selected_deadlines.json` con `evidence_origin=own_collector_ingestion_ledger`.
No se mezclan silenciosamente con los 193 testigos externos G35: el índice común
con distinción de origen queda para el siguiente gate.

El exportador standalone `collector_public_export.py` se ejecuta por stdin con
Python estándar en el host autorizado, apuntando al directorio raw `fpl` y al
corte fijo; solo escribe el tar en stdout. El ledger se consulta con
`collector_ledger_export.py` dentro del worker provisionado, con las credenciales
readonly existentes. No requiere copiar secretos ni desplegar código. La API no
monta ese secreto; no se modificaron sus mounts para obtener acceso.

```bash
python -m experiments.data_ground_truth.collector_public_export \
  --unpack "$COLLECTOR_PUBLIC_ARCHIVE" --out "$COLLECTOR_PUBLIC_RAW_ROOT"
python -m experiments.data_ground_truth.collector_public_audit \
  --base-root "$EXPERIMENTS_ROOT" --raw-root "$COLLECTOR_PUBLIC_RAW_ROOT" \
  --ledger "$COLLECTOR_READONLY_LEDGER" --out "$COLLECTOR_PUBLIC_AUDIT_ROOT"
```

La exportación aceptada es `collector-public-export-v2.tar.gz`, su contenido
`raw-collector-public-v2` y la auditoría `collector-public-audit-v2`, reproducida
en `v3`. Reporte, capturas e índice se reprodujeron byte por byte. Suite:
**1.517 passed, 1 skipped, 79 deselected**. Pruebas cubren exclusión de cuerpos de
cuenta, manifiestos originales, corrupción, traversal de tar, cierre de ingesta,
deadline exclusivo y conflictos de ledger. [Resultados G36](results-g36.json).
GT v5, entrenamiento, controles y despliegues de producción permanecen intactos.

## Gate G37: índice común de evidencia de calendarios

`calendar_evidence_index.py` reproduce G35 y G36 desde sus fuentes y exige igualdad
byte por byte de los reportes e índices parentales antes de combinarlos. Revalida
los objetos normalizados referenciados y su población de 380 fixtures. Cada entrada
conserva la evidencia original y distingue `external_publication` de
`own_collector_ingestion_ledger`; una eventual superposición cuenta una jornada,
pero conserva ambas evidencias. No se eleva su admisión a entrenamiento.

Resultado: **195/199 deadlines** (193 externos y dos del ledger propio), frente a
193 en el índice exclusivamente externo. Cobertura por temporada: 2020/21 parcial
6/6; 2021/22 36/38; 2022/23 37/38; 2023/24, 2024/25 y 2025/26 38/38; 2026/27 2/3.
Faltan 2021/22 GW31–32, 2022/23 GW23 y 2026/27 GW1.

La frescura se informa por reloj: 93/193 fuentes externas tienen edad de commit
hasta 48 horas (máximo 798,83 horas); las dos internas tienen inicio de captura
hasta 48 horas (máximo 2,384 horas). No se suman esos relojes como una medición
homogénea de captura API. Cobertura de calendario no acredita replay causal completo.

Artefactos fuera de Git: `calendar-evidence-index-v1/{report.json,calendar_evidence.json}`
y reproducción `calendar-evidence-index-v2/`, bajo la raíz de experimentos. Ejecución:

```bash
python -m experiments.data_ground_truth.calendar_evidence_index \
  --base-root /home/jzuluaga/code/orbital-lab/mova-fpl-experiments \
  --out /home/jzuluaga/code/orbital-lab/mova-fpl-experiments/calendar-evidence-index-v1
```

Reporte e índice reproducidos byte por byte. **1.521 passed, 1 skipped,
79 deselected**. Pruebas de solapamiento, duplicados, deadline exclusivo, orden de
relojes, evidencia no acreditada y ventanas faltantes. Producción y GT v5 intactos.
[Resultados G37](results-g37.json).

## Gate G38: fuentes oficiales de reglas históricas

`historical_rule_evidence.py` adquiere por GET diez artículos de Premier League y
conserva **946.819 bytes de HTML** en `raw-official-rules-v1`, fuera de Git. El
catálogo revisado `historical_rule_sources.json` fija IDs oficiales, títulos,
fechas visibles, localizadores y treinta afirmaciones estructuradas. Cada
localizador debe aparecer exactamente una vez en el texto visible, excluyendo
scripts y estilos. No se ejecutan instrucciones extraídas de las páginas.

La evidencia documental parcial cubre seis temporadas: 2017/18, 2019/20,
2021/22, 2022/23, 2024/25 y 2025/26. Incluye sustitución de All Out Attack por Free
Hit, reinicio 2019/20, Free Hit adicional 2021/22, ventana del Mundial 2022,
retención y límite de transferencias 2024/25, Assistant Manager y chips por
mitades de 2025/26, además de la reposición a cinco transferencias para AFCON.
La matriz cruza doce temporadas con seis dimensiones: **18/72 celdas** tienen
alguna evidencia documental. Esa cifra no mide porcentaje de reglas completas;
las demás celdas se declaran `not_collected`, sin herencia entre temporadas.

Fuentes primarias, fijadas por URL y hash en el manifiesto externo:

- [Free Hit 2017](https://www.premierleague.com/en/news/436425).
- [Reinicio 2019/20](https://www.premierleague.com/en/news/1678559).
- [Free Hit adicional 2021/22](https://www.premierleague.com/en/news/2425494).
- [Cambios 2022/23](https://www.premierleague.com/en/news/2667633) y
  [FAQ del Mundial](https://www.premierleague.com/en/news/2890870).
- [Cambios 2024/25](https://www.premierleague.com/en/news/4058895),
  [revelación del Assistant Manager](https://www.premierleague.com/en/news/4193484)
  y [detalle del chip](https://www.premierleague.com/en/news/4192707).
- [Cambios 2025/26](https://www.premierleague.com/en/news/4373187) y
  [transferencias por AFCON](https://www.premierleague.com/en/news/4362102).

Los artículos se descargaron en septiembre de 2026: su fecha visible no acredita
que estos mismos bytes estuvieran publicados entonces. `available_at=null`,
`eligible_replay=false` y `eligible_training=false` permanecen explícitos. Las
horas editoriales de deadlines tampoco sustituyen al calendario auditado: por
ejemplo, el FAQ del Mundial contiene horas diferentes para el deadline de GW16.
Se conservan esos textos, sin elegir silenciosamente una hora como canónica.
La revelación de un chip durante una temporada tampoco se aplica retroactivamente
a GW1. Las afirmaciones son anotaciones revisadas, no reglas ejecutables.

```bash
python -m experiments.data_ground_truth.historical_rule_evidence \
  --spec experiments/data_ground_truth/historical_rule_sources.json \
  --raw-root /home/jzuluaga/code/orbital-lab/mova-fpl-experiments/raw-official-rules-v1 \
  --out /home/jzuluaga/code/orbital-lab/mova-fpl-experiments/official-rules-audit-v2 \
  --offline
```

La primera extracción `official-rules-audit-v1` se rechazó por un localizador
ambiguo y se conserva sin admitir. El catálogo se corrigió a una frase única;
`official-rules-audit-v2` es la auditoría aceptada y `v3` la reproduce byte por
byte en reporte, evidencia y manifiesto. **1.525 passed, 1 skipped, 79 deselected**.
Pruebas: localizadores ambiguos/ausentes, fecha ausente, exclusión de scripts,
modo offline, corrupción de objetos y restricción de URL. GT v5 y producción
intactos. [Resultados G38](results-g38.json).

## Gate G39: calendarios oficiales en PDF y dificultad de pretemporada

Fuentes adquiridas por la primitiva GET del proyecto, fuera de Git en
`raw-official-calendar-pdf-v1`:

- [Calendario FA 2013/14](https://www.thefa.com/~/media/Files/PDF/Leagues/PL-fixtures1314.pdf):
  82.680 bytes, SHA-256 `f12d8c479c8118fba89b3e93ee27e8ebbaec2f5fc9ea7ef84ad899b331aa6f12`.
- [FDR oficial PL 2025/26](https://resources.premierleague.pulselive.com/premierleague/document/2025/06/18/ce06a980-45c1-4e10-b9ae-88a08262b869/FDR-2025-26.pdf):
  91.365 bytes, SHA-256 `a4c113029d0d6de143f89b60937fc6b8d00b45670a85eda3c18a16fc93f07db5`.

`official_calendar_pdf.py` valida hashes y tamaños, conserva texto, coordenadas y
rellenos vectoriales con PyMuPDF 1.26.4 en un entorno aislado de `uv`. El parser
2013/14 consume todas las líneas y verifica veinte clubes y cada cruce dirigido
exactamente una vez: **380 partidos**, quince páginas. Las horas quedan locales,
sin zona inferida ni GW FPL inventada. Esto no incorpora una temporada de etiquetas
FPL: es evidencia adicional de calendario.

Para FDR, se verificaron visualmente las dos mitades de la tabla y su leyenda.
El parser usa las coordenadas de GW1–38 y cuarenta etiquetas de filas para extraer
**760 celdas**. Cada cruce debe tener reciprocidad local/visitante y el conjunto
completo debe formar 380 partidos únicos. Los valores de dificultad proceden del
color exacto de la leyenda, sin aproximación al color más cercano. Distribución:
190 celdas de dificultad 2, 399 de dificultad 3, 152 de dificultad 4 y 19 de
dificultad 5; cero colores sin clasificar. La leyenda incluye 1, sin celdas con
ese valor en esta versión.

El contraste con el bootstrap GW1 2025/26 y el calendario G23 final confirma
**380/380 cruces**. Hay **10 diferencias de GW** (observaciones por club, no diez
partidos) y **304 diferencias de dificultad** en las 760 observaciones frente a
la versión final. `reference-comparison.json` conserva ambos valores y los hashes
de las referencias. Es diagnóstico retrospectivo; no corrige el PDF con valores
posteriores. FDR de junio es una versión de pretemporada, no una serie temporal.

Fechas de creación PDF y cabeceras HTTP `Last-Modified` se conservan como metadata,
no como pruebas de publicación. Permanecen `available_at=null`,
`eligible_training=false` y `eligible_replay=false`. El índice G37 sigue en
195/199; este gate no acredita nuevos deadlines.

```bash
uv run --no-project --with pymupdf==1.26.4 python \
  -m experiments.data_ground_truth.official_calendar_pdf extract \
  --source /home/jzuluaga/code/orbital-lab/mova-fpl-experiments/raw-official-calendar-pdf-v1 \
  --out /home/jzuluaga/code/orbital-lab/mova-fpl-experiments/official-calendar-pdf-extraction-v2
python -m experiments.data_ground_truth.official_calendar_pdf audit \
  --source /home/jzuluaga/code/orbital-lab/mova-fpl-experiments/official-calendar-pdf-extraction-v2 \
  --out /home/jzuluaga/code/orbital-lab/mova-fpl-experiments/official-calendar-pdf-audit-v2 \
  --base-root /home/jzuluaga/code/orbital-lab/mova-fpl-experiments
```

Extracción y auditoría `v2` reproducidas byte por byte en `v3`, incluyendo todos
sus JSON. Las versiones `v1` previas al contraste final se conservan. Los tests
cubren población, duplicados, autocruces, reciprocidad, rechazo de líneas sin
parsear y rellenos ausentes o ambiguos. **1.529 passed, 1 skipped, 79 deselected**;
GT v5 y producción intactos. [Resultados G39](results-g39.json).

## Gate G40: conciliación de FPL Discovery 2014/15 contra el GT vigente

La [página del autor](https://fpldiscovery.wordpress.com/summary_14_15/) enlaza un
[CSV público de puntos 2014/15](https://docs.google.com/spreadsheets/d/1wndu_erCorQ1G3eBaLax9AJ891HD6ZtHfPLzT3986kw/export?format=csv).
Se adquirieron 3.526.952 bytes, SHA-256
`f00f3723720c61bd74c0023b065af2fa590aef0d13470676f698ca485dd7bf79`,
en `raw-fpl-discovery-v1/points-2014-15.csv`, fuera de Git. La fecha de descarga
no acredita disponibilidad histórica ni independencia de linaje frente al RData.

**Resultado frente al GT v5 vigente:** 24.876 filas, cero nuevas; 665 códigos de
jugador coincidentes y **46 códigos candidatos** para 674 filas existentes sin
minutos jugados. Quince campos por fila, **373.140 celdas**, coinciden sin
excepciones. El paquete GT v5 completo se verifica antes de leer su partición;
sus hashes se conservan en `gt_v5_comparison`. Ningún candidato pendiente tiene
corroboración en dos partidos jugados. No se modifica GT v5 ni se reclama una
mejora nueva de identidades de jugadores con participación.

La auditoría también conserva la comparación contra la base original de
identidades: veinte campos numéricos y tres textuales, 572.148 celdas iguales,
486 códigos ya resueltos y 225 candidatos frente a esa base antigua. Tres de
ellos tienen evidencia de código, club y partidos jugados: Matthew Phillips
(50229, 25 partidos), Steven Davis (17339, 35) y Kelvin Davis (3673, siete).
**Los tres ya estaban resueltos en GT v5.** Esa corroboración confirma trabajo
previo; no añade 114 identidades de fila al GT actual. El reporte distingue
`reference_scope=original_identity_baseline_before_GT_v5` y `gt_v5_comparison`.

Las claves incluyen ID de temporada, GW, fecha local y fixture textual: ID+GW
no basta en jornadas dobles. Precios se comparan mediante conversión decimal
exacta por diez; ownership conserva su separador decimal. Los perfiles finales
permanecen retrospectivos. Las 3.307 observaciones PL sin minutos se excluyen de
corroboración de participación, sin imputarlas a cero. Los códigos declarados
son candidatos y no reemplazan automáticamente las identidades del GT.

```bash
python -m experiments.data_ground_truth.discovery_2014 \
  --base-root /home/jzuluaga/code/orbital-lab/mova-fpl-experiments \
  --out /home/jzuluaga/code/orbital-lab/mova-fpl-experiments/discovery-2014-audit-v4
```

La primera corrida se detuvo ante minutos ausentes. Las auditorías v2/v3 sólo
comparaban la base inicial; se conservan como alcance parcial y no prueban
progreso frente al GT vigente. **v4 es la auditoría aceptada**, reproducida byte
por byte en v5: reporte, candidatos y ambos archivos de diferencias. La prueba
de regresión impide contar como nuevo un código ya resuelto en GT v5.
**1.534 passed, 1 skipped, 79 deselected**.
[Resultados G40](results-g40.json).

## Gate G41: corroboración de perfiles y GT v6 experimental

`discovery_identity_enrichment.py` reproduce G40 contra el GT v5 y contrasta sus
46 candidatos con **7.338 perfiles de jugadores** de diez archivos FPL
`players_raw.csv`, temporadas 2016/17–2025/26. Verifica hashes, unicidad de código
por temporada y exclusión de managers. La igualdad exige código declarado y
nombre completo; sólo normaliza Unicode, mayúsculas y espacios, sin fuzzy matching.

Resultado: **19 códigos corroborados**, un caso con variante de nombre que
requiere revisión (Matthew/Matt Macey) y 26 sin perfil en estas diez fuentes.
Que un código aparezca en otra partición del GT no sustituye al perfil completo:
el descubrimiento de G40 incluía además 2015/16 y tenía un alcance diferente.
Se conservan todos los perfiles coincidentes y las variantes observadas.

GT v6 experimental:
`58e2e08833a157601e3e6bf75ea71adcd84211bf96a2139e9490b8936aa9e7cb`.
Deriva del GT v5
`1d111a458c9074fcd7ec2da516e82d9d1984600f6f057716112b92e855240df4`,
que se conserva intacto. Cambia exclusivamente `official_player_code`,
`source_official_player_code` e `identity_key` en **223 filas existentes** de
2014/15. Son filas sin minutos jugados; no se crean ejemplos ni se alteran puntos,
minutos, componentes, jornadas, tiempos o particiones de entrenamiento/evaluación.

2014/15 pasa de 24.202 a **24.425 filas con código enlazado**. Quedan 451 filas y
27 jugadores con identidad limitada a la temporada. El conjunto sigue teniendo
**303.126 filas de jugadores en doce temporadas**, con 322 filas de managers
separadas. Todos los archivos ajenos a la partición 2014/15 y al manifiesto se
comparan byte por byte contra el padre. El verificador mantiene la restricción de
entidades de jugador también para v6.

Los perfiles de temporadas posteriores se usan únicamente para identidad estable.
No se incorporan sus precios, estados, ownership, resultados futuros ni otros
campos como features. No se acredita replay anterior al deadline, no se entrena
un modelo ni se promueve el paquete al runtime productivo. El puntero documental
[current-labels.json](current-labels.json) identifica el GT experimental vigente;
no cambia configuraciones de benchmarks ni despliegues.

```bash
python -m experiments.data_ground_truth.discovery_identity_enrichment \
  --base-root /home/jzuluaga/code/orbital-lab/mova-fpl-experiments \
  --out /home/jzuluaga/code/orbital-lab/mova-fpl-experiments/discovery-identity-enrichment-v2 \
  --datasets-root /home/jzuluaga/code/orbital-lab/mova-fpl-experiments/training-datasets
```

La auditoría v2 se reproduce en v3. El paquete se reconstruye en una raíz
independiente (`g41-reproduced-datasets`) y sus quince archivos son idénticos.
La primera versión exploratoria se conserva, pero no es el paquete vigente.
Las pruebas cubren códigos sin nombre coincidente, variantes no admitidas,
colisiones, conservación de valores, población y exclusión de managers en v5/v6.
**1.539 passed, 1 skipped, 79 deselected**.
[Resultados G41](results-g41.json).

## Gate G42: perfiles históricos adicionales y GT v7 experimental

`discovery_profile_extension.py` reproduce G41 y audita los **620 perfiles** del
[dump histórico FPL de clwatkins](https://github.com/clwatkins/fantasy_premier_league/blob/aa8e6b99aac8f02cc85bb07ac0c3a3a655c0e993/Data/FPL_API_Dump.json),
archivado en la capa raw. SHA-256 del cuerpo:
`b057bf1a5567d9b474fa59b5303beb5d8a3a186f85837ccf1b3c406942ec0639`.
La fuente conserva fecha de descarga, revisión y disponibilidad histórica desconocida.
El diccionario usa nombres visibles como claves; podría omitir homónimos y no
se considera prueba de población completa.

De los 27 candidatos pendientes en GT v6, **tres coinciden por código y nombre
completo**: Doneil Henry, Jamal Blackman y Lewis Kinsella. Cambian únicamente
los tres campos de identidad de **30 filas existentes**. Quedan 23 jugadores
sin perfil y Matthew/Matt Macey como variante pendiente: **24 jugadores y 421
filas** con identidad limitada a 2014/15. La partición tiene 24.455 de 24.876
filas con código enlazado (98,31 %). No se incorporan estadísticas futuras como
features ni se inventa una fecha de disponibilidad.

GT v7 experimental:
`d4baf849fb4a051be103f8c469e61a4753edb0b4004f980a000fe5c86ef573db`.
Conserva GT v6 como padre inmutable, las **303.126 filas de jugadores de doce
temporadas** y las 322 filas separadas de managers. No cambia puntos, minutos,
particiones temporales, modelos o producción. El puntero documental
[current-labels.json](current-labels.json) señala esta versión experimental.

```bash
python -m experiments.data_ground_truth.discovery_profile_extension \
  --base-root /home/jzuluaga/code/orbital-lab/mova-fpl-experiments \
  --out /home/jzuluaga/code/orbital-lab/mova-fpl-experiments/discovery-profile-extension-v1 \
  --datasets-root /home/jzuluaga/code/orbital-lab/mova-fpl-experiments/training-datasets
```

Reporte, identidades y cambios se reprodujeron byte por byte en
`discovery-profile-extension-v2`. Los quince archivos del paquete son idénticos
al reconstruirlo en `g42-reproduced-datasets`. La suite verifica también que v7
rechaza managers en particiones de jugadores: **1.542 passed, 1 skipped,
79 deselected**. [Resultados G42](results-g42.json).

La búsqueda complementaria de fuentes públicas no acreditó otra temporada FPL
completa en este gate. El triage de Orbix Research devolvió resultados ajenos al
tema, por lo que no se incorporan como evidencia científica. El siguiente foco
con mayor utilidad para el benchmark es la cobertura y frescura anterior al
deadline, y la semántica de los acumulados de GW1. Resolver identidades de filas
sin minutos no demuestra una mejora predictiva ni cierra esas brechas.

## Gate G43: período de los acumulados de GW2

`gw2_period.py` contrasta el bootstrap seleccionado antes de GW2 con la suma de
resultados finales de GW1 del GT v7. Verifica el paquete y el hash del artefacto
G31; conserva códigos, fuentes y deadlines. No vuelve a acreditar testigos de
publicación ni convierte las etiquetas finales en datos disponibles históricamente.

| Temporada | Jugadores con 13 componentes iguales | Sin referencia GW1 |
| --- | ---: | ---: |
| 2021/22 | 554 | 5 |
| 2022/23 | 573 | 7 |
| 2023/24 | 658 | 8 |
| 2024/25 | 616 | 9 |
| 2025/26 | 690 | 8 |
| 2026/27 | 0 | 616 |

De 3.744 filas auditadas, **3.091 coinciden en las 40.183 celdas comparables**:
minutos, puntos, goles, asistencias, porterías a cero, goles encajados, penaltis
parados y fallados, tarjetas amarillas y rojas, paradas, bonus y BPS. No hay
diferencias en este contraste. Los 37 códigos históricos sin fila GW1 permanecen
desconocidos; los 616 actuales carecen de temporada de referencia en GT v7.
No se crean filas de cero minutos ni ceros para componentes ausentes.

Junto con G32, el resultado respalda el cambio de período de los acumulados
entre GW1 y GW2 para los campos y jugadores comparados. **No prueba xG, starts,
DefCon, autogoles, otras jornadas ni igualdad entre la versión final y todas las
versiones intermedias de la API**. No autoriza calcular deltas GW1→GW2 sin una
regla explícita de período. GT v7, producción y modelos permanecen intactos.

```bash
python -m experiments.data_ground_truth.gw2_period \
  --performance-root /home/jzuluaga/code/orbital-lab/mova-fpl-experiments/bootstrap-performance-v2 \
  --package /home/jzuluaga/code/orbital-lab/mova-fpl-experiments/training-datasets/d4baf849fb4a051be103f8c469e61a4753edb0b4004f980a000fe5c86ef573db \
  --out /home/jzuluaga/code/orbital-lab/mova-fpl-experiments/gw2-period-v1
```

Reporte y comparaciones reproducidos byte por byte en `gw2-period-v2`.
Pruebas de exclusión de semanas futuras, ausencias, nulos y códigos ambiguos;
suite completa: **1.544 passed, 1 skipped, 79 deselected**.
[Resultados G43](results-g43.json). El siguiente contraste debe ampliar las
jornadas respetando aplazamientos y tiempos de partido; sumar por número de GW
sin esa precaución no constituye un estado causal.

## Gate G44: conciliación de acumulados por jornada y fecha

`cumulative_period.py` amplía G43 a las ventanas posteriores a GW1 con temporada
presente en GT v7. Contrasta trece componentes con dos referencias retrospectivas:
la suma de GWs anteriores y la suma de partidos con kickoff anterior al deadline.
No confunde kickoff con finalización o publicación. Registra partidos cercanos
al cierre y excluye la inferencia de totales completos cuando faltan fechas.
Los jugadores sin referencia y los componentes nulos permanecen desconocidos.

```bash
python -m experiments.data_ground_truth.cumulative_period \
  --performance-root /home/jzuluaga/code/orbital-lab/mova-fpl-experiments/bootstrap-performance-v2 \
  --package /home/jzuluaga/code/orbital-lab/mova-fpl-experiments/training-datasets/d4baf849fb4a051be103f8c469e61a4753edb0b4004f980a000fe5c86ef573db \
  --out /home/jzuluaga/code/orbital-lab/mova-fpl-experiments/cumulative-period-v1
```

Los resultados finales pueden incluir correcciones posteriores al snapshot. Una
diferencia no se clasifica automáticamente como error de ingesta ni se repara
con información futura. El timestamp nominal del snapshot y su prueba de
publicación siguen siendo contratos separados. El gate no incorpora features,
no modifica GT v7 y no promueve modelos o cambios productivos.

Resultado: **191 ventanas y 138.830 estados**, seis temporadas con referencia
(2020/21 parcial, 2021/22–2025/26 con 37 ventanas posteriores a GW1 por temporada).
2026/27 queda sin referencia. En las ventanas medidas, ambos criterios seleccionan
las mismas filas; no hay tiempos ausentes ni kickoffs dentro de las cuatro horas
anteriores al cierre. Esto describe el GT final, no demuestra el calendario
conocido por el operador en cada fecha.

**138.544 estados coinciden**, 283 carecen de código en la referencia y tres
presentan diferencias: **1.801.102 celdas iguales y nueve diferentes**. Entre los
estados con minutos positivos en el snapshot, 91.496 coinciden y tres difieren;
la conclusión no descansa sólo en filas de cero minutos.

Las tres diferencias corresponden al código 487117, elemento 123, en GW25–27 de
2024/25: el snapshot tiene 17 minutos, un punto y dos goles encajados menos que
la referencia final en cada ventana. Las magnitudes y campos coinciden con la
corrección del fixture 239 conservada en [G14](results-g14.json). Es evidencia
compatible con una revisión de resultados; no prueba la hora exacta de la
corrección ni autoriza sobrescribir los snapshots históricos.

Reporte y comparaciones comprimidas se reprodujeron byte por byte en
`cumulative-period-v2`. **1.547 passed, 1 skipped, 79 deselected**.
[Resultados G44](results-g44.json). La siguiente investigación debe localizar
la transición de esas tres celdas en el archivo raw y conservar sus versiones,
sin introducir el GT final como feature anterior al deadline.

## Gate G45: versiones observadas de la discrepancia de Ferguson

`correction_history.py` parte de las excepciones selladas de G44 y verifica GT v7,
manifest raw, inventario auditado y cada objeto comprimido. Extrae los tres campos
del jugador correcto, comprueba entidad/código y calcula residuos contra sus
partidos finales anteriores al reloj nominal del archivo. La hipótesis UTC sólo
sirve para ese diagnóstico; `available_at` permanece desconocido.

La ventana explícita va desde catorce días antes del primer deadline afectado
hasta treinta días después del último: **31 de enero–27 de marzo de 2025**.
Se auditan **219 capturas**, 146 iguales y 73 diferentes. Hay cuatro observaciones
con kickoff del jugador dentro de las cuatro horas anteriores (una igual, tres
diferentes); el margen es una señal diagnóstica, no prueba de finalización.

| Transición nominal observada | Antes | Después |
| --- | --- | --- |
| 12 febrero 18:31 → 13 febrero 01:46 | 234 minutos, 20 puntos, 7 goles encajados | 217 minutos, 19 puntos, 5 goles encajados |
| 2 marzo 18:29 → 3 marzo 01:52 | 287 minutos, 22 puntos, 5 goles encajados | 304 minutos, 23 puntos, 7 goles encajados |

Los valores **ya coincidían, disminuyeron y después volvieron a coincidir**.
Esto precisa G44: el archivo no muestra simplemente una carga inicial tardía.
Las magnitudes coinciden con el fixture 239 de G14, pero ni su causa ni el
instante exacto de modificación en la API quedan demostrados. Las dos transiciones
adicionales del 1 de febrero están próximas al kickoff y se conservan aparte.
Los estados de ambas fronteras, campos, residuos y hashes quedan en el reporte;
las 219 observaciones completas permanecen fuera de Git en `timelines.json`.

```bash
python -m experiments.data_ground_truth.correction_history \
  --base-root /home/jzuluaga/code/orbital-lab/mova-fpl-experiments \
  --package /home/jzuluaga/code/orbital-lab/mova-fpl-experiments/training-datasets/d4baf849fb4a051be103f8c469e61a4753edb0b4004f980a000fe5c86ef573db \
  --out /home/jzuluaga/code/orbital-lab/mova-fpl-experiments/correction-history-v1
```

Reporte y timeline reproducidos byte por byte en `correction-history-v2`.
**1.549 passed, 1 skipped, 79 deselected**. Pruebas de residuos sin mutar el
valor observado, ausencia, identidad incorrecta, fecha desconocida, campo ausente
y reloj con zona no esperado. [Resultados G45](results-g45.json).
GT v7, features y producción no cambian. Acreditar publicación de las fronteras
sigue siendo un paso separado; la trayectoria nominal no concede admisión causal.

## Gate G46: componentes adicionales por partido

`supplemental_components.py` verifica los 7.365 CSV individuales archivados y GT
v7. Conserva nueve campos adicionales en un artefacto separado, con hash y fuente
por fila, unión exacta por temporada/elemento/fixture y concordancia de GW y
kickoff con zona horaria. No incorpora estos campos a las etiquetas ni a las
features del runtime. Valores CSV vacíos, columnas ausentes, ceros y dominios
inválidos tienen estados diferentes; `starts` por partido sólo admite 0 o 1.
Los testigos contradictorios quedan en cuarentena, sin escoger uno en silencio.

**253.417 filas enlazadas**, 415 claves en cuarentena: 78 discrepancias de kickoff
en 2021/22 y 337 sin referencia de jugador (322 en 2024/25 y quince en temporadas
anteriores). Hay además catorce filas del GT 2019/20–2020/21 sin fuente individual
correspondiente. Las dos temporadas iniciales del GT no tienen CSV de esta fuente;
no se declara cobertura suplementaria para ellas.

| Campos | Temporadas con columna y valores numéricos válidos | Filas por campo |
| --- | --- | ---: |
| Starts, xG, xA, xG encajado, xG involvement | 2022/23–2025/26 | 113.260 |
| Defensive contribution | 2025/26 | 29.747 |
| Recuperaciones, entradas, despejes/bloqueos/intercepciones | 2016/17–2018/19 y 2025/26 | 97.683 |

Los campos defensivos antiguos no son columnas de ceros: recuperaciones tiene
9.367, 9.348 y 9.425 valores positivos en 2016/17, 2017/18 y 2018/19,
respectivamente. Eso acredita contenido numérico, **no equivalencia de definición
entre épocas**. La contribución defensiva nueva sigue separada. Para starts,
cada una de las cuatro temporadas recientes contiene 8.360 filas con valor 1.
El reporte conserva conteos de valores positivos y ceros de los nueve campos
por temporada. No hay valores inválidos entre las filas enlazadas de esta corrida.

```bash
python -m experiments.data_ground_truth.supplemental_components \
  --raw-root /home/jzuluaga/code/orbital-lab/mova-fpl-experiments/raw-player-gameweeks \
  --package /home/jzuluaga/code/orbital-lab/mova-fpl-experiments/training-datasets/d4baf849fb4a051be103f8c469e61a4753edb0b4004f980a000fe5c86ef573db \
  --out /home/jzuluaga/code/orbital-lab/mova-fpl-experiments/supplemental-components-v3
```

Reporte, componentes comprimidos y cuarentena reproducidos byte por byte en
`supplemental-components-v4`. Las corridas v1/v2 anteriores no incluían el conteo
de actividad de valores y se conservan como auditoría parcial. **1.551 passed,
1 skipped, 79 deselected**. [Resultados G46](results-g46.json).

El siguiente contraste debe evaluar estos componentes contra los snapshots y
medir revisiones/precisión decimal, sin suponer disponibilidad anterior al deadline
ni convertir automáticamente métricas antiguas en puntos de reglas modernas.
GT v7 y producción permanecen intactos; no se añade una temporada completa nueva.

## Gate G47: acumulados suplementarios y precisión decimal

`supplemental_cumulative.py` compara los nueve componentes G46 con los snapshots
G31, usando `Decimal` y sumas por kickoff estrictamente anterior al deadline.
Sólo compara temporadas cuya referencia de jugadores está totalmente enlazada;
los snapshots GW1 se excluyen por su semántica diferente. No cuenta filas
incompletas como ceros. El estado acumulado avanza por deadlines crecientes y
conserva nulos/ausencias de cualquier partido de la suma.

**110.018 estados en 148 ventanas de cuatro temporadas**. En 2023/24 hay
144.060 celdas comparables exactamente iguales; en 2025/26, 260.154. Los campos
sin columna y jugadores sin referencia permanecen fuera de esa afirmación.
En 2024/25 hay 132.466 celdas iguales y nueve diferentes de Ferguson en GW25–27:
xA y xG involvement difieren −0,01 (seis celdas), y xG encajado −0,74 (tres).

La categoría `within_rounding_bound` no significa igualdad. Sólo cuando los
valores tienen precisión numérica compatible con centésimas se calcula el margen
`0,005 × (n_partidos + 1)`, bajo la hipótesis explícita de redondeo al más cercano
en cada partido y en el acumulado. Una diferencia fuera del margen se conserva
como tal; una precisión distinta no se fuerza a esa hipótesis. Starts y los
contadores enteros no reciben tolerancia.

2022/23 requiere tratamiento por tramo:

- GW2–15: starts y los cuatro campos esperados están ausentes del snapshot.
- GW16: 383 discrepancias de starts; no se explican por redondeo.
- GW17–21: xG incluye discrepancias con precisión incompatible con centésimas.
- GW22: xG tiene 173 diferencias dentro del margen hipotético, 534 igualdades y
  27 jugadores sin referencia.
- GW23–38: todas las celdas xG comparables coinciden exactamente.

En el total 2022/23 se conservan 9.260 celdas `different` (incluye enteros y
precisión fuera de la hipótesis), 1.573 fuera del margen y 2.773 dentro del margen.
No se atribuye una causa única ni se rellenan los campos ausentes con resultados
finales. La auditoría mide consistencia retrospectiva, no publicación ni causalidad.

```bash
python -m experiments.data_ground_truth.supplemental_cumulative \
  --supplemental-root /home/jzuluaga/code/orbital-lab/mova-fpl-experiments/supplemental-components-v3 \
  --performance-root /home/jzuluaga/code/orbital-lab/mova-fpl-experiments/bootstrap-performance-v2 \
  --out /home/jzuluaga/code/orbital-lab/mova-fpl-experiments/supplemental-cumulative-v1
```

Reporte y comparaciones reproducidos byte por byte en `supplemental-cumulative-v2`.
**1.553 passed, 1 skipped, 79 deselected**. Pruebas de aritmética decimal,
tolerancia separada de igualdad, enteros, precisión distinta y desconocidos.
[Resultados G47](results-g47.json). GT v7 y runtime intactos; el siguiente gate
debe investigar la introducción y precisión de estos campos en 2022/23 antes de
proponer un contrato de features por temporada y ventana.

## Gate G48: introducción y precisión de campos en 2022/23

`supplemental_field_history.py` verifica **1.458 snapshots** de 2022/23, desde
5 julio 2022 hasta 5 julio 2023 según el reloj nominal de los archivos. Para cada
población de jugadores clasifica los cinco campos (starts y cuatro métricas
esperadas) como ausentes, todos cero, positivos compatibles con centésimas,
positivos con precisión inferior a una centésima o población parcial/inválida.
La compatibilidad se calcula por valor numérico, sin confundir ceros decimales
finales de una cadena con precisión efectiva.

| Frontera nominal entre capturas | Cambio observado |
| --- | --- |
| 9 noviembre 2022, 12:54 → 18:30 | Ausente → columna poblada sólo con ceros |
| 12 noviembre 2022, 06:29 → 12:41 | Ceros → valores positivos; métricas esperadas con fracciones de centésima |
| 30 enero 2023, 12:39 → 18:24 | Métricas esperadas pasan a valores compatibles con centésimas |

Cada campo estuvo ausente en **508 capturas**, seguido por **once capturas sólo
con ceros**. Starts tiene luego 939 capturas con valores positivos; cada métrica
esperada tiene 317 capturas de precisión inferior a la centésima y 622
compatibles con centésimas. Los reportes conservan las fronteras, hashes, conteos
positivos/cero y estados de toda la población. Las observaciones completas
permanecen fuera de Git y se verifican por hash.

El snapshot G31 seleccionado para GW16 está fechado nominalmente el 12 noviembre
2022 a las 06:29 y su deadline es 11:00Z: conserva la población de ceros. La primera
captura positiva observada es 12:41. Esa secuencia precisa G47, **sin acreditar
la hora exacta de cambio de la API, disponibilidad externa ni que todo cero sea
un placeholder**. No se rellenan los snapshots con el resultado posterior.

Como contexto adicional se archivó la [explicación oficial de xG en Fantasy](https://www.premierleague.com/en/news/3118332),
cuya página consultada declara 22 septiembre 2023. Explica xG, xA y xGI, pero no
establece las fechas de introducción de 2022/23. Cuerpo HTML de 88.787 bytes,
SHA-256 `a9ff43ecdad043b693a294014b21abef39920f5cbab911c8c110525286929e8f`;
fecha de descarga y disponibilidad desconocida en [resultados G48](results-g48.json).
No se utiliza como prueba de publicación histórica de las capturas.

```bash
python -m experiments.data_ground_truth.supplemental_field_history \
  --raw-root /home/jzuluaga/code/orbital-lab/mova-fpl-experiments/raw-bootstrap-snapshots \
  --audit-root /home/jzuluaga/code/orbital-lab/mova-fpl-experiments/bootstrap-audit-v1 \
  --out /home/jzuluaga/code/orbital-lab/mova-fpl-experiments/supplemental-field-history-v1
```

Reporte y observaciones reproducidos byte por byte en
`supplemental-field-history-v2`; hash del HTML archivado verificado.
**1.555 passed, 1 skipped, 79 deselected**. Pruebas de ausencia/cero/positivo,
precisión numérica frente a formato y población parcial o inválida.
GT v7, modelos y producción no cambian. Falta convertir esta evidencia en una
admisión por campo y ventana, manteniendo separadas semántica y publicación.

## Gate G49: filtro observable sin selección por resultados futuros

`snapshot_field_screening.py` construye un filtro preliminar por campo sin leer
etiquetas finales, discrepancias G44/G47 ni la segmentación retrospectiva G48.
**La igualdad con el GT no puede ser un criterio de inclusión histórica**: usarla
para seleccionar sólo snapshots correctos condicionaría el experimento a
información posterior. Los diagnósticos retrospectivos siguen separados.

El gate reproduce la selección y sus testigos externos de publicación, luego
reproduce la extracción numérica G31. Exige igualdad de todos los artefactos
padres y liga cada fila a su hash y deadline antes de evaluar:

- Publicación externa acreditada o pendiente.
- Campo observado válido, ausente, nulo o inválido.
- GW1 con período todavía no resuelto.
- Para starts y métricas esperadas: población entera en cero pese a minutos
  positivos observados en ese mismo snapshot. Es sospecha para revisión, no
  prueba de placeholder ni regla que rellene valores.

Resultado: **143.720 estados, 199 ventanas y 3.161.840 celdas**.
**2.423.700 `screen_pass`**, 738.140 `review_required`. Los motivos se solapan:
642.042 ausencias de campo, 79.684 celdas GW1, 41.074 sin publicación acreditada
y 3.305 con población cero sospechosa. Este último motivo localiza exactamente
los cinco campos de los 661 jugadores de GW16 2022/23 sin consultar el GT.

`screen_pass` **no es admisión a entrenamiento** ni certificación semántica. El
resultado conserva `training_admitted=false`; período, identidad, calendarios,
reglas y publicación/captura requieren sus contratos separados. Una discrepancia
retrospectiva como Ferguson no es por sí misma motivo para excluir el dato raw.
La fecha de publicación es un límite acreditado, no la hora exacta de captura API.

```bash
python -m experiments.data_ground_truth.snapshot_field_screening \
  --base-root /home/jzuluaga/code/orbital-lab/mova-fpl-experiments \
  --out /home/jzuluaga/code/orbital-lab/mova-fpl-experiments/snapshot-field-screening-v1
```

Reporte y filtro comprimido reproducidos byte por byte en
`snapshot-field-screening-v2`; cada corrida revalida publicación y extracción raw.
**1.557 passed, 1 skipped, 79 deselected**. Las pruebas conservan idéntico filtro
al cambiar una etiqueta informativa de igualdad retrospectiva, y separan población
cero, período y publicación. [Resultados G49](results-g49.json).
GT v7 y producción permanecen intactos. El filtro prepara la admisión experimental;
no modifica por sí mismo la configuración de benchmarks ni el entrenamiento.

## Gate G50: inventario consolidado e integridad de la capa raw

`raw_corpus_inventory.py` inspecciona todos los directorios `raw*/manifest.json`
del corte y verifica tamaño y SHA-256 de cada objeto referenciado. Cada copia
física se verifica, incluso cuando comparte hash con otro conjunto. Los exports
del collector sólo permiten los cuerpos públicos bootstrap/fixtures: los hashes
de payload de cuenta son referencias y no se leen ni exportan esos cuerpos.
También verifica el paquete señalado por `current-labels.json`, incluidos hash
del manifiesto y contrato de etiquetas.

| Medida al corte | Resultado |
| --- | ---: |
| Conjuntos con manifiesto, incluidas versiones anteriores | 21 |
| Registros en esos manifiestos | 32.423 |
| Objetos físicos referenciados verificados | 27.214 |
| Bytes físicos referenciados | 1.585.532.426 |
| Contenidos únicos por SHA-256 | 24.462 |
| Bytes únicos de esos contenidos | 1.396.855.878 |
| Conjuntos con errores de adquisición declarados o conteo esperado incumplido | 0 |
| Archivos de otros formatos inventariados | 141 |
| Bytes de esos otros archivos | 49.817.739 |

Los otros archivos proceden de siete carpetas: búsquedas, documentos oficiales,
PDFs, FPL Discovery y evidencia de inspección. Se registra su hash actual como
**línea base observada**, no como validación contra un manifiesto de adquisición.
Los hashes no equivalen a nuevas observaciones deportivas ni resuelven licencias,
semántica o disponibilidad anterior al deadline.

`raw-history-differential` conserva **seis archivos de objeto no referenciados**
por su manifiesto actual. Se cuentan como deuda de procedencia, fuera de los
objetos referenciados verificados; no se eliminan ni se admiten como datos nuevos.
El resto de los conjuntos no tiene objetos sin referencia. El siguiente paso
es localizar los registros de adquisición de esos seis cuerpos antes de
completar su inventario verificable.

El paquete experimental vigente sigue siendo GT v7, 303.126 filas de jugadores
2014/15–2025/26 y 322 de managers. La integridad del paquete se comprobó de nuevo.
El inventario conserva por conjunto los repositorios, hashes de manifiestos,
conteos y tipo de registro, sin mezclar versiones anteriores con adquisiciones
nuevas. Esta comprobación no es una auditoría fresca de salud de producción.

```bash
python -m experiments.data_ground_truth.raw_corpus_inventory \
  --base-root /home/jzuluaga/code/orbital-lab/mova-fpl-experiments \
  --label-pointer experiments/data_ground_truth/current-labels.json \
  --out /home/jzuluaga/code/orbital-lab/mova-fpl-experiments/corpus-inventory-v4
```

Reporte y tres índices se reproducen byte por byte en `corpus-inventory-v5`.
Las corridas anteriores se conservan como exploratorias/parciales. El comando
rechaza ubicar su salida dentro del espacio `raw*`, para no inventariarse como
fuente. **1.560 passed, 1 skipped, 79 deselected**. Pruebas de corrupción del
mismo tamaño, digest inválido, allowlist de cuerpos públicos y separación de
salida/entrada. [Resultados G50](results-g50.json). Sin entrenamiento, promoción
ni cambios en producción; las brechas de cobertura y causalidad siguen abiertas.

## Gate G51: clasificación de los seis auxiliares Differential

La inspección precisa el hallazgo G50: los seis archivos fuera del manifiesto
son **tres pares con sufijos SQLite `-wal`/`-shm`**, asociados por nombre a cuerpos
`.db3` ya registrados. `sqlite_sidecar_audit.py` verifica los hashes de las bases,
su cabecera SQLite y los hashes/tamaños de cada auxiliar. No atribuye qué proceso
los creó ni los incorpora al manifiesto como nuevas adquisiciones.

Los tres WAL tienen **cero bytes**. Los tres SHM tienen 32.768 bytes cada uno y
el mismo hash. Como explica la [documentación SQLite WAL](https://www.sqlite.org/wal.html),
SQLite puede usar archivos auxiliares incluso al abrir una base en modo de sólo
lectura; la opción [immutable](https://www.sqlite.org/uri.html) tiene un contrato
separado. El lector Differential vigente ya utiliza `mode=ro&immutable=1`,
`trusted_schema=OFF`, `query_only=ON` y `quick_check`; no se modificó ese lector.

Para cada base se hizo una copia temporal **sin auxiliares**, se comprobó la
igualdad de las tres tablas permitidas y se verificó que la lectura no cambiara
la copia ni creara archivos adicionales:

| Base registrada | player_match | player_season | fixture |
| --- | ---: | ---: | ---: |
| diffgen14b.db3 | 42.049 | 5.014 | 1.520 |
| diffgen15_final.db3 | 44.426 | 5.933 | 1.900 |
| diffgen16.db3 | 64.718 | 6.561 | 2.280 |

Las tablas son iguales en contenido, no sólo en conteo, y el reporte conserva
sus hashes. Estos conteos incluyen datos parciales/superpuestos ya auditados;
**no son nuevas etiquetas completas**. Los originales, manifiesto y seis
auxiliares conservaron sus hashes antes/después. Un WAL no vacío impide este
ensayo de lectura independiente y exige revisión; nunca se ignora o elimina
para forzar un resultado.

```bash
python -m experiments.data_ground_truth.sqlite_sidecar_audit \
  --raw-root /home/jzuluaga/code/orbital-lab/mova-fpl-experiments/raw-history-differential \
  --out /home/jzuluaga/code/orbital-lab/mova-fpl-experiments/sqlite-sidecar-audit-v1
```

Reporte reproducido byte por byte en `sqlite-sidecar-audit-v2`.
**1.561 passed, 1 skipped, 79 deselected**. Prueba de asociación a padre SQLite,
WAL no vacío y nombres no clasificados. [Resultados G51](results-g51.json).
G50 sigue describiendo seis archivos no referenciados físicamente; G51 resuelve
su clasificación como auxiliares conservados. No hay nuevas fuentes, temporadas,
entrenamiento ni cambios productivos en este gate.
