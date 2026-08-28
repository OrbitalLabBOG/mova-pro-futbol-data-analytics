---
type: gameweek-closeout
name: "FPL 2026/27 GW1 — settlement y review retrospectivo"
created: 2026-08-27
updated: 2026-08-27
tags: [mova, fpl, gw1, settlement, review, feedback, model]
status: verified
season: 2026-27
gameweek: 1
---

# GW1 — settlement y review retrospectivo

## Veredicto

GW1 quedó oficialmente `finished + data_checked`. `losmillosFPL` (entry `3609854`) obtuvo
**50 puntos**, exactamente el promedio oficial, con rank de jornada **4.383.525**. Los quince
jugadores tuvieron minutos, no hubo autosubs y la banca produjo 25 puntos.

No existió un batch de proyección inmutable anterior al deadline de GW1. Por eso este cierre es
un diagnóstico retrospectivo y no crea una fila falsa en `model_evaluation_runs`: el primer
scorecard causal del servicio analítico será GW2.

## Resultado y contrafactual pareado

| Escenario sellado antes del deadline | xP | Puntos reales | Error total |
| --- | ---: | ---: | ---: |
| Decisión humana revisada | 38,5 | 50 | +11,5 |
| MILP puro `points-1.1.0`, horizonte 3 | 50,83 | 62 | +11,17 |

La intervención humana costaba **−12,33 xP** según el propio modelo y entregó **−12 puntos**
frente al MILP puro sobre los mismos resultados. La capitanía no causó la diferencia: Haaland y
Gibbs-White hicieron dos puntos cada uno. El contrafactual correcto usa Dango/O.Dango, elemento
95; no debe confundirse con Abdoul Ouattara, elemento 592.

La alineación humana tuvo MAE base por jugador de 3,461 y Brier P60 de 0,1599 en sus quince
activos. El escenario MILP tuvo 2,928 y 0,1043 respectivamente. Ambos totales quedaron por debajo
del resultado real, pero una jornada no alcanza para recalibrar ni promover un modelo.

## Qué aprendimos

1. Siete jugadores de la plantilla con P60 inferior a 60% alcanzaron 60 minutos: Calafiori,
   Mosquera, Tzolis, Bruno, Haaland, Sangaré y Bobby Thomas. El prior de rol de cold start necesita
   un experimento shadow con señales contemporáneas; no un parche entrenado contra GW1.
2. El override humano incorporó información válida, pero la aplicó de forma inconsistente:
   protegió titulares con P60 baja y dejó en banca a Sangaré (14) y Rodon (6). En adelante todo
   override amplio debe mostrar el diff, el costo xP y el contrafactual puro antes de aprobarse.
3. La banca de 25 puntos no prueba que Bench Boost debiera jugarse. Su xP ex ante era 7,60 y la
   política correcta preservó el chip. Inferir estrategia de chips desde el resultado observado
   sería hindsight bias.
4. El oracle de la misma plantilla fue 69 manteniendo a Haaland capitán y 81 permitiendo elegir
   capitán con información perfecta. Es un techo descriptivo, nunca un objetivo de optimización.
5. El analytics service estaba configurado por defecto con `1.0.0` mientras la decisión y los
   artefactos aprobados usan `1.1.0`. El cierre alinea ambas releases antes del batch final de GW2.

## Memoria operativa

La migración SQLite `004` y PostgreSQL `006` agregan:

- `gameweek_settlements`: resultado factual y fuente oficial;
- `gameweek_reviews`: review causal o retrospectivo con estado de causalidad;
- `review_player_outcomes`: quince jugadores en decisión y comparador;
- `change_proposals`: hipótesis versionadas, criterio de aceptación y estado.

El cierre también backfillea ciclo, snapshot, team state, señales de research, intervención,
decisión y jugadores, estrategia de chips, ejecución manual, siete verificaciones y auditoría.
`trace.db` recibe una corrida reconciliada y la atribución pareada 50 vs 62. El package canónico es
`decisions/fpl/2026-27/gw01_closeout.json`.

## Propuestas

| Nivel | Propuesta | Estado |
| --- | --- | --- |
| C2 | calibrar minutos de cold start durante las primeras tres GWs | propuesta; shadow, sin autopromoción |
| C1 | exigir comparación pareada antes de overrides humanos amplios | propuesta; medir mínimo seis intervenciones |
| C1 | alinear analytics con minutes/points `1.1.0` | aceptada y verificada por nuevo batch GW2 |

Ninguna conclusión de una sola GW autoriza reentrenamiento, cambio de chip o promoción de
autonomía.
