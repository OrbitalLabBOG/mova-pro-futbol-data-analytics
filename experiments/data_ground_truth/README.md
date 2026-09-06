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
