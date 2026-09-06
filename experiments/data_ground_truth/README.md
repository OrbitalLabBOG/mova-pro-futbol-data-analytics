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
