---
title: Laboratorio causal de estrategia FPL de largo horizonte
status: experimental
owner: MOVA Fantasy
experiment_id: EXP-MOVA-2026-003
updated: 2026-09-04
---

# Long-horizon uncertainty lab

Este laboratorio busca maximizar puntos esperados de temporada, no acertar un
partido aislado. Vive en una rama/worktree independiente y no publica artefactos
ni modifica la selección activa del runtime.

## Contrato experimental

- **Control:** algoritmo vigente, reentrenado causalmente por fold, estado solo
  de la temporada objetivo, horizonte 3 y repetición del xP del rival actual.
- **Desarrollo:** 2021-22, 2023-24 y 2024-25. Se excluye 2022-23 porque
  incluyó transferencias ilimitadas entre GW16 y GW17 por el Mundial, transición
  que este simulador aún no representa.
- **Holdout sellado:** 2025-26, que solo se abre después de congelar el candidato.
- **North star:** `PVA-38`, diferencia pareada de puntos reales de temporada
  contra el control sobre los mismos partidos.
- **Incertidumbre:** CRPS, coberturas 50/80/90%, bootstrap pareado por bloques y
  penalización de transferencias sustentadas por alta desviación predictiva.
- **Fragilidad:** `paired_policy_influence_v1` informa leave-one-season-out,
  extremos por GW y si una sola jornada invierte el signo de una temporada. Es
  un guardrail de interpretación y nunca una regla para excluir resultados.
- **Eventos:** `threat` y `creativity` históricos como proxies jugador-partido.
  Los eventos WhoScored solo cubren parte de 2025-26 y permanecen como ablation
  secundaria; no pueden justificar promoción multitemporada.
- **Promoción:** prohibida en este experimento. Primero se socializa el holdout y
  se requiere autorización explícita.

Cada fold entrena minutos y puntos únicamente con temporadas anteriores al
objetivo. La última temporada pasada calibra minutos y no entra al clasificador
base. En replay, `multi_season_as_of` conserva estado de jugadores entre
temporadas sin mezclar ninguna fila del futuro.

## Iteración 3

`EXP-MOVA-2026-001` demostró que incorporar la carrera completa al estado
perjudicó 2021-22, incluso con recencia. La iteración 2 conserva el estado
season-only del control y prueba estrategia intersemanal sin esa variable.
`EXP-MOVA-2026-002` se detuvo de forma segura al encontrar los activos `AM` del
chip Assistant Manager en 2024-25. Esta iteración repite el protocolo bajo un
nuevo hash, excluye esos activos especiales del universo de jugadores y conserva
su evidencia cruda para auditoría; no simula retrospectivamente ese chip.

## Ablaciones vigentes

| Variante | Estado | Calendario | Horizonte | Eventos | Estabilidad |
|---|---|---|---:|---|---|
| `control_h3` | temporada | rival actual repetido | 3, decay .84 | no | no |
| `season_fixture_h3` | temporada | por fixture | 3, decay .84 | no | no |
| `season_fixture_h6` | temporada | por fixture | 6, decay .84 | no | no |
| `season_fixture_h6_events` | temporada | por fixture | 6, decay .84 | sí | no |
| `season_fixture_h6_events_stable` | temporada | por fixture | 6, decay .84 | sí | sí |

La secuencia evita atribuir a “IA” una mejora que en realidad venga de corregir
el cold start o de mirar el rival correcto.

## Ejecución

```bash
python -m experiments.long_horizon.run manifest --fpl-db /ruta/fpl_canonical.db
python -m experiments.long_horizon.run screen-events --fpl-db /ruta/fpl_canonical.db
python -m experiments.long_horizon.run select-policy --fpl-db /ruta/fpl_canonical.db
python -m experiments.long_horizon.run holdout --fpl-db /ruta/fpl_canonical.db
```

La evidencia generada queda fuera del repo, en el directorio hermano
`../mova-fpl-experiments/EXP-MOVA-2026-003/`:
manifest con hashes, artefactos por fold, predicciones, trazas, puntos por GW,
bootstrap y acta del holdout.

## Adaptador de shadow vivo

El mismo proyector fixture-a-fixture usado por este replay vive ahora en
`mova_fpl.engine.projection.fixture_horizon_projection`; el laboratorio solo lo
adapta a `ProjectionBundle`. La CLI viva puede adjuntar el contrafactual con
`--strategy-shadow season_fixture_h3`, sin modificar el candidato operativo
seleccionado. El tick únicamente añade ese flag cuando
`MOVA_ENABLE_LONG_HORIZON_SHADOW=1`; el default es apagado.

El artefacto `mova-strategy-shadow-v1` contiene ambos fingerprints, diferencias
de xP/transferencias/hits y todas las matrices de proyección de tres GW. Esto
permite medir el comportamiento vivo con el information set exacto del deadline,
en vez de reconstruirlo retrospectivamente.

`mova_fpl.analytics.strategy_shadow` completa el ciclo después de cada jornada:
puntúa el par contra resultados oficiales, lo contrasta con la decisión manual
y agrega únicamente gameweeks consecutivas. Al tercer cierre el estado es
`review_required`, nunca promoción automática. Los resultados quedan dentro del
review durable y en un artefacto de gate identificado por hash.

La primera observación local también puede cerrarse sin conectar el sandbox a
producción. `experiments.long_horizon.live_settlement` verifica los hashes del
bundle congelado, consulta únicamente endpoints GET oficiales y se niega a
puntuar antes de `finished + data_checked`. El resultado es content-addressed,
declara cero writes de producción y admite como evidencia manual un JSON
explícito o los picks públicos observados después del deadline:

```bash
python -m experiments.long_horizon.live_settlement probe \
  --experiment-dir ../mova-fpl-experiments/EXP-MOVA-2026-008
python -m experiments.long_horizon.live_settlement settle \
  --experiment-dir ../mova-fpl-experiments/EXP-MOVA-2026-008 \
  --team-id "$MOVA_FPL_TEAM_ID"
```

Para que ese acumulado corresponda a una política y no a decisiones aisladas,
`mova_fpl.engine.virtual_shadow` arrastra por separado squad, precios de compra,
banco y transferencias libres del control y el candidato. Una discontinuidad o
un hash inválido inicia una nueva racha y queda visible en el artefacto.

## Límites conocidos

1. El calendario histórico conoce la asignación final de aplazamientos (`L-01`).
2. La CRPS Normal aproxima una distribución discreta e inflada en cero.
3. En dobles jornadas se suman varianzas condicionales; falta modelar la
   correlación compartida de disponibilidad.
4. Solo cuatro temporadas modernas tienen club y posición completos para un
   replay de política comparable.
5. El chip Assistant Manager 2024/25 no se modela; sus activos `AM` quedan fuera
   de plantillas y baselines, igual que `element_type == 5` en el runtime vivo.

Estas limitaciones son gates de interpretación, no permisos para ajustar sobre
el holdout.

## Iteración 4: eventos aislados sobre h3

`EXP-MOVA-2026-004` elimina un confusor pendiente: en la iteración anterior los
proxies `threat` y `creativity` solo se evaluaron dentro del horizonte seis. El
módulo `experiments.long_horizon.event_h3` compara control, `season_fixture_h3`
y `season_fixture_h3_events` manteniendo todo salvo los proxies constante. El
peso 0,45 se hereda congelado; el challenger solo puede abrir la evaluación
temporal 2025-26 si mejora la media y gana al menos dos de tres temporadas de
desarrollo. Este experimento tampoco puede promover ni ejecutar decisiones.

## Iteración 5: incertidumbre discreta

`EXP-MOVA-2026-005` conserva intacta la media y la política `h3`, pero reemplaza
para evaluación la Normal simétrica por una PMF empírica de puntos enteros. El
calibrador busca vecinos históricos dentro de la misma posición usando xP,
desviación y número de fixtures; por construcción puede asignar masa explícita
a cero y a resultados negativos. La selección usa folds temporales y CRPS
discreto. Su salida es diagnóstica y no entra al optimizador ni al runtime.

`EXP-MOVA-2026-006` entrena el artefacto causal para 2026-27 con las cuatro
temporadas ya cerradas y lo conecta de manera opcional al shadow. El artefacto
es NPZ tipado sin pickle, queda enlazado por SHA-256 y nunca modifica la xP que
consume el optimizador.

## Iteración 12: valor terminal de FT

`EXP-MOVA-2026-012` prueba el sesgo de truncamiento del horizonte tres sin
alargarlo ni modificar xP. El challenger asigna un valor de continuación fijo
de un punto a cada transferencia libre disponible después de la última GW de la
ventana. Es una sola hipótesis preregistrada —no un barrido— y siempre menor que
el coste de cuatro puntos de un hit. Debe mejorar la media y ganar al menos tres
de cuatro temporadas de desarrollo antes de abrir la evaluación 2025-26.

## Iteración 13: cambio de régimen entre temporadas

`EXP-MOVA-2026-013` aísla una divergencia encontrada en el runtime vivo: sus
modelos están entrenados con varias temporadas, pero el estado de inferencia
permanece congelado en el cierre 2025-26 y no incorpora las jornadas ya cerradas
de 2026-27. El laboratorio compara ese control exacto contra cuatro tratamientos
causales del cambio de temporada: reinicio con observaciones actuales, fallback
individual, cola de cuatro jornadas y arrastre completo.

La selección usa log-loss multiclase de minutos en GW2-GW8 de tres temporadas
de desarrollo, con Brier/ECE como guardrails. El candidato solo llega a 2025-26
si también mejora puntos reales con la política `season_fixture_h3`. No se usan
datos sintéticos para eficacia y ninguna salida modifica el runtime o FPL.

## Iteraciones 14–16: verificación viva y ruta promovible

`EXP-MOVA-2026-014` confirmó el defecto con un contrafactual predeadline exacto:
el estado heredado dejaba a Haaland en P(60') 0,439 y a Mamadou Sangaré en
0,181; al anexar GW1–GW2 oficiales y asentadas subieron a 0,777 y 0,781. La
decisión cambió sin hits y mejoró 4,79 xP en la jornada bajo la política h3.

`EXP-MOVA-2026-015` probó recalibración online por prior shift. La mejora de
desarrollo fue minúscula y el holdout empeoró Brier P(60') y el slice de
jugadores managerialmente relevantes, por lo que fue rechazada.

`EXP-MOVA-2026-016` llevó el tratamiento ganador a la ruta real de snapshot y
CLI: cada snapshot guarda por hash todos los `event-live` previos que estén
`finished + data_checked`, el runtime rechaza jornadas incompletas, DGW
agregadas o filas futuras, y el default pasa a `append_closed`. La corrida GW3
usó 29.747 filas previas + 1.236 actuales, 652 candidatos, equipo privado exacto
y produjo tres candidatos válidos con cero escrituras. El modo heredado queda
disponible solo como `--history-state previous_only` para rollback explícito.

## Iteraciones 17–20: ensemble y transferencias entre clubes

`EXP-MOVA-2026-017` modela explícitamente la duda entre continuidad y reinicio
mediante un ensemble convexo. El peso 50/50 fue seleccionado únicamente en
desarrollo: mejoró log-loss de minutos en las tres temporadas y Brier P(60').
En política obtuvo deltas +148, -111 y +82; en 2025-26 mejoró log-loss en 0,00354,
Brier P(60') en 0,00050 y sumó +29 puntos. Pasa el gate preregistrado, pero el
IC95 cruza cero y la victoria externa cambia al retirar su mejor GW: queda como
challenger de shadow, no como reemplazo automático.

`EXP-MOVA-2026-018` detectó además que bootstrap solo conserva el club actual:
para jugadores transferidos después de una GW, mapear retrospectivamente el
fixture con ese club puede inventar rival y localía. Esa observación quedó
superseded. El runtime ahora identifica el desacuerdo, consulta únicamente para
esos IDs el `element-summary` oficial, guarda cada respuesta por hash y recupera
fixture, lado y club histórico. Sin evidencia individual, omite la fila y lo
declara en calidad.

`EXP-MOVA-2026-019` repitió el ciclo con un snapshot nuevo: reparó las 25 filas
afectadas, no omitió ninguna y conservó 1.236 filas actuales. La CLI produjo una
acta válida. El shadow `fixture_h3` superó al planner vigente por 1,87 xP en GW3
y evitó un hit: Mosquera y Rodon por Tarkowski y Egan, capitán Haaland.

`EXP-MOVA-2026-020` repitió el ensemble 50/50 sobre el estado reparado. Produjo
exactamente el mismo fingerprint que `append_full + fixture_h3`. El acuerdo es
tranquilizador, pero una sola observación viva no autoriza promoción. La
separación vigente es deliberada: `append_closed` y la recuperación de club sí
son arreglos promovibles del information set; el ensemble y `fixture_h3`
continúan en shadow hasta acumular jornadas consecutivas y settlement real.
