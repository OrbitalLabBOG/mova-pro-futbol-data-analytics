---
title: Benchmark interno de progreso analítico MOVA
status: experimental
owner: MOVA Fantasy
---

# Benchmark interno v1

[Tabla histórica de progreso](snapshots/v1/REPORT.md) ·
[Snapshot portable](snapshots/v1/catalog.json) · [Registro de comparaciones](registry.json)

El benchmark consolida evidencia previa sin reentrenar ni promover modelos.
Incluye 23 directorios (21 IDs, una reproducción y un preflight fallido), 11 grupos
pareados de política y siete paneles predictivos. Una carpeta no implica una
corrida terminada. Los experimentos sin adaptador de métricas quedan inventariados,
con hashes de metadata y sin puntuación inventada.

La métrica principal es **PVA-38**: diferencia de puntos netos de temporada frente
al control del mismo grupo. Cada tabla muestra temporadas, media, victorias,
derrotas e IC95 cuando su fuente tiene el mismo par de deltas. El bootstrap no
se recalcula desde totales ni se presenta como evidencia nueva. CRPS, log-loss,
Brier y calibración viven en paneles separados, conservando población y fuente.

## Reproducir y verificar

Desde la raíz del repositorio (Python 3.13 del proyecto; sólo stdlib para este CLI):

```bash
python -m experiments.benchmark.run \
  --root ../mova-fpl-experiments \
  --output experiments/benchmark/snapshots/v1 --check
```

`--check` reconstruye en memoria, verifica hashes y compara ambos archivos, sin
escribir. Un archivo ausente, evidencia alterada o una población no pareada falla.
Sin `--check`, el comando crea un snapshot nuevo; nunca sobrescribe uno existente.
La lectura del reporte y JSON versionados no necesita artefactos externos.

La auditoría sólo verifica bytes de los JSON fuente importados y manifests.
No certifica automáticamente todos los modelos/CSV/SQLite citados por esos JSON.
Los hashes de código/dataset declarados se conservan como declaraciones históricas,
no como prueba de que se reejecutó el código. La importación de totales antiguos
no reconstruye decisiones; el adaptador de replay sí verifica 38 GW y suma neta.

## Cómo incorporar la siguiente corrida

1. Antes de ejecutarla, congelar su hipótesis, control y protocolo en Git.
   Registrar dataset y corte temporal, reglas/puntuación/chips por temporada,
   estado inicial de plantilla/banco/FT, política de precios, universo elegible,
   presupuesto y versión de solver, semillas, historia disponible y folds.
   Explicitar qué componente es la variable experimental y cuáles se mantienen.
2. Guardar manifest, resultados, modelos y trazas bajo un ID nuevo. El runner
   correspondiente sigue ejecutando el experimento; este CLI sólo consolida.
3. Añadir a `registry.json` un grupo con ID/version, control, fase, temporadas,
   archivos, adaptador y, si existe, ruta del bootstrap pareado. Preferir el
   adaptador `replays`: exige GW1..38 y puntos netos. Para métricas predictivas,
   registrar la población, nombres originales y rutas explícitas.
4. Crear `snapshots/v2` (o la siguiente versión), revisar el diff y ejecutar
   `--check` más `pytest -q`. Conservar v1 y el resultado rechazado/incompleto.
5. Para comparar contra otra generación, reejecutar ambos bajo el mismo protocolo
   y registrarlos juntos en un grupo nuevo. No unir por temporada ni por dataset
   compartido: el mismo CSV no garantiza las mismas condiciones de decisión.

`comparison_sha256` sella especificación, manifest y fuentes de cada grupo.
Un cambio de fuente cambia la identidad. Las tablas ordenan sólo dentro del
mismo grupo; la media no demuestra significancia ni reemplaza gates del harness.
No hay score compuesto que mezcle calibración, puntos esperados y puntos reales.
2025-26 permanece diagnóstico ya consultado en nuevos experimentos.

## Próximo benchmark común

El siguiente replay comparativo debe congelar el control actual y contrastar
`fixture_h3`, ensemble y `season_value` con idéntico estado, reglas y presupuesto.
Primero resolver catálogos históricos y disponibilidad temporal del calendario;
no copiar los ocho chips actuales a temporadas con reglas diferentes. El rango
histórico comparable se publica después de verificar esas condiciones.

Esta consolidación no ejecuta ese nuevo replay ni configura MLflow. Cuando se
incorpore tracking, importará IDs, grupos y hashes de este contrato; no cambiará
la definición de progreso ni la autoridad de promoción del runtime.
