---
title: "EXP-MOVA-2026-021 — participación y valor de temporada"
status: experimental
updated: 2026-09-04
owner: MOVA Fantasy
---

# Participación y valor de temporada

El experimento compara el baseline `append_full + fixture_h3` con un modelo de
participación reciente. Usa cuatro folds temporales: 2021-22, 2023-24 y 2024-25
para desarrollo; 2025-26 como diagnóstico externo ya consultado anteriormente.
No se presenta 2025-26 como un nuevo holdout intacto.

El clasificador conserva las ramas 0 / 1–59 / 60+ y añade siete variables de
estado causal: observaciones de temporada, titularidad reciente, participación
reciente, frecuencia reciente de 60+, minutos recientes, diferencia frente al
historial y ausencia explícita del dato de titularidad. La última temporada
anterior al objetivo calibra el clasificador; no entra a su ajuste base.

La segunda hipótesis es un valor de continuación conjunto de chips. Aprende
vectores de oportunidades contrafactuales predeadline de temporadas anteriores
sobre estados de plantilla reales del replay. Estos valores son incrementos de
objetivo del solver, no resultados de partidos futuros ni ganancias realizadas.
La recurrencia de Bellman compara gastar uno de los chips con esperar, hasta
GW38, conservando competencia entre chips, ventanas y prohibiciones. Una jornada
lejana sin calendario conocido no se interpreta como una jornada en blanco.

Esta aproximación aprende una distribución estacionaria de oportunidades
normalizadas por estructura. Su estado de continuación es inventario y tiempo;
no es un modelo completo de transiciones de todos los jugadores. El MILP de
plantilla sigue siendo rodante h3. No se afirma optimalidad global de temporada.

## Reproducibilidad

Desde este worktree, con Python 3.13 y dependencias del proyecto:

```bash
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 python -m experiments.season_value.run predict \
  --fpl-db /ruta/fpl_canonical.db
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 python -m experiments.season_value.run replay \
  --fpl-db /ruta/fpl_canonical.db --season 2023-24 --variant baseline --collect-opportunities
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 python -m experiments.season_value.run replay \
  --fpl-db /ruta/fpl_canonical.db --season 2024-25 --variant baseline --collect-opportunities
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 python -m experiments.season_value.run replay \
  --fpl-db /ruta/fpl_canonical.db --season 2025-26 --variant season_value
```

Variantes: `runtime_matrix`, `baseline` (fixture h3), `participation`,
`season_value` (solo planificador) y `combined`. Las tres temporadas de desarrollo
no soportan chips históricos completos: se liquidan sin chips. La recolección de
sus oportunidades usa un inventario hipotético aislado y no aplica chips a la
trayectoria. Solo 2025-26 admite el replay conjunto completo del catálogo actual.

El directorio hermano `mova-fpl-experiments/EXP-MOVA-2026-021` contiene manifest,
folds, predicciones, métricas, oportunidades, trazas SQLite y puntos por GW. El
manifest fija h3, decay 0,84, top-20, seed 42 y tres segundos CBC por solve. Es un
presupuesto computacional comparativo; una solución factible no necesariamente
prueba optimalidad. Los modelos se identifican por SHA-256. No sobrescribir un
modelo de otra fuente; para un protocolo nuevo usar otro directorio/ID.

## Gates y límites

La evaluación de eficacia usa resultados oficiales históricos, no datos
sintéticos. Las pruebas unitarias sí usan microinstancias conocidas para
comprobar causalidad, inventario y reversión. La selección exige utilidad de
política, además de calibración: mejorar Brier no permite promover un modelo que
pierde temporadas. Mantener todas las derrotas y reportar intervalos pareados.

Los fixtures históricos conservan la ubicación final de aplazamientos. La
identidad histórica contiene colisiones de nombres (por ejemplo Ben Davies);
el challenger no inventa identidades para separarlas. No utiliza noticias,
lesiones o alineaciones históricas sin timestamps verificables. Las etiquetas
predictivas de esta corrida excluyen DGW agregadas para no confundir dos partidos
con una probabilidad por fixture.

La inspiración metodológica es la decisión secuencial bajo observación parcial
[Matthews et al., AAAI 2012](https://ojs.aaai.org/index.php/AAAI/article/view/8259)
y la evaluación de utilidad decisional
[Elmachtoub y Grigas](https://arxiv.org/abs/1710.08005).
No se implementa ni se atribuye una réplica de esos algoritmos.

## Integración

`mova model train --architecture participation_v2` publica un bundle candidato
inmutable con ledger, sin cambiar el activo. Su promoción conserva el lifecycle
de [mejora continua](../../docs/operations/continuous-improvement.md).

El manifest `mova-season-value-shadow-v1` sella versiones y hashes de ambos
modelos, temporada, samples del planificador y `selected_for_execution=false`.
`MOVA_SEASON_VALUE_SHADOW_MANIFEST` y `MOVA_SEASON_VALUE_SHADOW_SHA256` habilitan el
comparador a través del tick. Ambos brazos usan fixture h3, top-20 y el mismo
presupuesto de solver; el control conserva el modelo/planificador vigente.

Este shadow reemplaza al comparador h3 dentro del único slot estratégico, no a
la decisión operativa. Un cambio de manifest reinicia la secuencia de evidencia.
Guarda plantillas, precio de compra, banco, FT y chips separados por brazo;
restaura Free Hit y liquida hits/bonus de capitán/chips contra resultados oficiales.
El reviewer y el gate de shadow siguen sin promover automáticamente.

## Resultado de la corrida del 4 de septiembre

Se completaron 380 jornadas de replay de política más una reproducción
independiente de 38 jornadas. La evaluación predictiva cubrió 104.256 filas por
variante en cuatro temporadas (sin etiquetas DGW agregadas).

| Comparación | Resultado |
| --- | --- |
| Participación nueva vs control, desarrollo | −79 / −44 / −77 puntos; media −66,67; rechazada para promoción |
| Control fixture h3 + planner habitual, 2025-26 | 2.056 puntos, 6 hits, ocho chips usados |
| Matriz repetida + planner habitual, mismo presupuesto | 2.058 puntos, 18 hits |
| Fixture h3 + valor conjunto de chips, 2025-26 | **2.212 puntos**, 3 hits, ocho chips usados |
| Participación nueva + valor conjunto de chips | 2.122 puntos, 4 hits |

El planificador aislado ganó +156 puntos contra su control pareado, IC95 de
bootstrap por bloques de cuatro jornadas [+24, +263]. Ese intervalo es
condicional a una sola temporada histórica ya consultada y no incorpora toda
la incertidumbre de selección, calendario ni cambio de distribución. La
reproducción independiente obtuvo 2.212 puntos y los mismos fingerprints 38/38.

**Decisión:** conservar los modelos predictivos vigentes y desplegar únicamente
el challenger de estrategia en shadow. No promover el nuevo predictor de
participación: perdió las tres temporadas de desarrollo aunque mejoró el Brier
de minutos en las cuatro evaluadas. La combinación tampoco mejora al planificador
solo. No se cambiaron parámetros para eliminar esas derrotas.

[Resultados y hashes](results.json) conserva métricas, comparaciones, chips,
reproducción y hashes de los artefactos externos. El manifest de inferencia
versionado es [season-value-1.0.0.json](../../deploy/analytics/season-value-1.0.0.json).
La promoción activa requiere nueva evidencia prospectiva; no se fabrica un
settlement de GW3 mientras siga abierta.

## Acta del despliegue v0.7.0

Verificado el 4 de septiembre de 2026, 22:29–22:45 America/Bogota.
Código e imagen productivos: `dea98e20db44b05da7b426d0b4476f1cd5fca928`,
[PR #40](https://github.com/OrbitalLabBOG/mova-pro-futbol-data-analytics/pull/40).
Esta acta posterior sólo modifica documentación; no cambia la imagen desplegada.

- Suite y CI: 1.372 passed, 1 skipped, 79 deselected; compileall y Compose válidos.
- Doctor: healthy, 24 PASS, 0 WARN, 0 FAIL; API y PostgreSQL healthy.
- Workflow: cero violaciones; presupuesto dentro del límite, sin reservas huérfanas.
  Research y deliberación pendientes; scorecard 15/25 pass y 10 pending.
- Backup previo: `/opt/orbital/backups/mova-fpl/20260905T032248Z`,
  job `job_0fbcd58dde4242fb82045ee285d5e5d6`.
- Rollback disponible: imagen/revisión `161cfe131d89df9019560603cd457ad07d726c97`.
- Tick real completado: `job_66f55d6f5e3944e5a57cfe6f028f44bd`;
  envelope `envelope_3202871d23a71c12fde62ea7`.
- Manifest SHA-256:
  `e7687eb1eafebd4223ca41e645ddb789143e070eae2eb65d1ba418b340d96ccf`.
- Evidencia completa y reproducción archivadas en el VPS:
  `/var/lib/mova-fpl/artifacts/experiments/EXP-MOVA-2026-021/evidence.tar.gz`;
  SHA-256 `7a28bc5ee972b747dffeed60967f4a34dd090fbb3d7e9e6f9a6f1e220d821f30`,
  verificado después de copiar.

La corrida real produjo dos brazos válidos, sin violaciones. El candidato
reserva chips (51,48 xP inmediatos); el control propone BB (61,83 xP).
El valor estimado de continuación de reservar supera el de BB: 102,82 contra
101,34. Son valores del modelo, no puntos realizados ni garantía de superioridad.
El candidato conserva estado virtual independiente y `selected_for_execution=false`.
Los predictores activos siguen en 1.1.0; la cuenta sigue A0/shadow sin escrituras.

La cuenta real lleva 163 puntos en GW1 y GW2 cerradas (50 y 113), contra medias
oficiales de 50 y 81. GW3 permanece abierta: su ranking y puntuación provisional
no se usan como resultado final. Los 25 y 22 puntos de banca no representan
por sí solos arrepentimiento recuperable mediante una alineación legal.

El alcance implementado combina optimización de plantilla a tres jornadas con
valor conjunto de chips hasta GW38. No es todavía un modelo completo de transición
de plantillas, lesiones, precios y rivales para toda la temporada. La siguiente
mejora analítica debe comparar esas transiciones y su incertidumbre con este
control, usando evaluación temporal y evidencia prospectiva; no promover el
predictor rechazado ni interpretar este único backtest como garantía de ganar.
