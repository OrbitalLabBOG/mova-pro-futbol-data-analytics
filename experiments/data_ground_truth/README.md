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
