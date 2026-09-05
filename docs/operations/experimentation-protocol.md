---
title: Protocolo de experimentación y promoción del motor FPL
status: experimental
owner: MOVA Fantasy
updated: 2026-09-03
---

# Protocolo de experimentación del motor FPL

El registro de modelos existente sigue siendo la fuente de artefactos de
producción. No se añade MLflow remoto en esta etapa: el harness ya sella SHA de
Git, SHA del dataset, configuración, fold temporal, trazas y resultados. MLflow
local con SQLite solo se evaluará si el volumen de corridas vuelve insuficiente
la consulta del benchmark interno consolidado resulte insuficiente.

El [benchmark interno v1](../../experiments/benchmark/README.md) reúne el catálogo,
comparaciones pareadas y paneles predictivos. Su [tabla de progreso](../../experiments/benchmark/snapshots/v1/REPORT.md)
separa protocolos y fases; no permite un ranking global de puntuaciones incompatibles.
Antes de MLflow, toda nueva corrida debe registrar control, información disponible,
reglas, recursos y evidencia bajo ese contrato. Los snapshots anteriores se conservan.

## Unidad de evidencia

Una iteración válida tiene:

1. identificador inmutable;
2. una variable primaria frente al control;
3. dataset y código identificados por SHA-256/SHA;
4. temporadas de selección separadas del holdout;
5. métricas predictivas y métricas de política;
6. limitaciones y resultado `iterate`, `discard`, `hold` o `promote`;
7. autorización humana antes de mover cualquier artefacto activo.

## Gate de candidato

Un modelo no avanza por bajar MAE solamente. Debe mostrar simultáneamente:

- `PVA-38` positivo en promedio frente al control causal;
- mejora en más de una temporada de desarrollo;
- intervalo y downside del bootstrap reportados, aunque no sean concluyentes;
- CRPS y calibración sin degradación material;
- ausencia de fuga temporal y uso exclusivo de estado predeadline;
- replay completo con presupuesto, venta, transferencias, hits, banca y capitán;
- holdout abierto una sola vez después de congelar hiperparámetros.

Si el holdout falla, se inicia otro experimento con un nuevo identificador; no
se ajusta el mismo candidato mirando el resultado sellado.

## Promoción

`prepared` y `shadow` no cambian producción. La promoción necesita:

1. socialización de resultados con Julián;
2. aprobación explícita;
3. revisión técnica de Buitra si cambia arquitectura;
4. bundle y rollback verificables;
5. shadow en la jornada viva antes de tráfico operativo.

Hasta entonces el runtime sigue en lectura/sombra y la operación manual conserva
la última palabra.

## Sombra viva de `season_fixture_h3`

El candidato offline de `EXP-MOVA-2026-003` tiene un adaptador opt-in en el
runtime. `MOVA_ENABLE_LONG_HORIZON_SHADOW=1` añade al artefacto de candidatos un
par control/candidato con estas garantías:

- el `selected_candidate_key` continúa siendo `milp_baseline`;
- ambos brazos usan el mismo snapshot, bundle de modelos, plantilla, banco,
  transferencias libres y política sin chips al iniciar la prueba;
- el control repite el xP del rival inmediato y el candidato proyecta rival y
  localía fixture-a-fixture durante tres GW;
- `selected_for_execution=false` queda sellado en el envelope;
- las matrices completas de xP y desviación estándar quedan en el JSON para su
  liquidación posterior.

Después del primer deadline, control y candidato mantienen **ledgers virtuales
separados** de plantilla, precio de compra, banco y transferencias libres. Cada
GW aplica solo la primera acción de su brazo y sella el estado siguiente con
fingerprint; el tick solo restaura el envelope de la GW inmediatamente anterior
y verifica antes su SHA-256. Así el acumulado mide dos políticas receding-horizon
reales, no recomendaciones independientes sobre la plantilla manual.

El flag permanece en `0` por defecto y no es una promoción. Para superar el gate
se requieren tres deadlines consecutivos, revisión contra la decisión manual y
una nueva autorización explícita.

Al cerrar una GW, el review retrospectivo busca el último envelope del ciclo,
verifica el SHA-256 del archivo y liquida ambos brazos con el resultado oficial
`finished + data_checked`. Guarda:

- puntos reales con autosustituciones, capitán efectivo e hits;
- delta candidato − control y candidato − decisión manual;
- MAE, RMSE, sesgo y Spearman para ambos brazos;
- CRPS Normal y coberturas 50/80/90 del candidato;
- un gate acumulado sobre la racha más reciente de GW consecutivas.

Incluso al completar tres GW, el gate solo puede devolver `review_required` y
`promotion_authorized=false`. Una brecha entre jornadas reinicia la racha; un
envelope ausente, alterado o ejecutable queda como evidencia inválida y no se
rellena retrospectivamente.

### Distribución discreta opcional

`EXP-MOVA-2026-005` seleccionó una PMF empírica condicionada por posición, xP,
desviación y número de fixtures. `EXP-MOVA-2026-006` la empaqueta como NPZ
tipado, cargado con `allow_pickle=False`. Solo se adjunta al shadow cuando están
definidos `MOVA_LONG_HORIZON_UNCERTAINTY_ARTIFACT` y su SHA-256 esperado en
`MOVA_LONG_HORIZON_UNCERTAINTY_SHA256`.

La PMF conserva explícitamente el soporte entero, `p(cero)` y cuantiles. No
reemplaza la media usada por el MILP y declara
`optimization_mean_unchanged=true` y `selected_for_execution=false`. El
envelope verifica hash, soporte, elementos, normalización y correspondencia con
la xP antes de aceptarla. Después de la jornada, el settlement contrasta CRPS,
log score y Brier contra la Normal discretizada. Cualquier error invalida solo
el comparador opcional; el baseline operativo continúa sin cambios.
