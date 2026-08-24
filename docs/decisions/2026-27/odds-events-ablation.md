---
title: "MOVA FPL — ablación causal de odds y eventos"
date: 2026-08-24
status: experiment-kept-production-rejected
owner: MOVA Fantasy Fútbol Data Analytics
season: 2026-27
tags: [mova, fpl, model, odds, whoscored, experiment]
---

# Ablación causal de odds y eventos

## Veredicto

Las **odds pre-closing sí contienen señal predictiva útil**, sobre todo para la
probabilidad de portería a cero. Se conserva el branch experimental y se aprueba
`odds_cs` como candidato de la siguiente iteración. **No se modifica el modelo
productivo**: el replay legal h=3 todavía pierde 38 puntos frente al baseline.

Las features de eventos probadas —remates, remates en el área, grandes ocasiones y
toques en el área— **no aportan señal incremental confiable**. Se cierran en esta
forma y no pasan a la siguiente iteración.

| Decisión | Estado | Evidencia principal |
| --- | --- | --- |
| Odds para clean sheets | continuar experimento | mejora calibración, xP y ranking semanal |
| Odds para ataque | no promover aún | el efecto no supera ruido en el control semanal |
| Eventos agregados de equipo | rechazado | intervalos pareados cruzan cero; combinado elige exponente 0 |
| Cambio productivo | rechazado | replay legal nominal: 2.130 vs 2.168 |

## Qué modelo se auditó

El motor vigente no es una regresión monolítica de puntos. Primero estima tres
estados de minutos y luego suma componentes auditables: aparición, goles,
asistencias, portería a cero, goles encajados, contribución defensiva, bonus,
tarjetas, paradas y otros. Las tasas del jugador son históricas y encogidas hacia
priors de posición; el contexto de partido proviene de una fuerza de equipo causal.

Antes de este experimento:

- las odds estaban recolectadas, pero desconectadas del xP;
- los eventos WhoScored se utilizaban para validar contribución defensiva, no como
  contexto de ataque/defensa;
- un script legacy no versionado mezclaba variables del mismo partido y agregados
  no temporales. No se reutilizó porque violaba la barrera causal.

El experimento cambia exclusivamente las intensidades de gol esperadas del partido.
Minutos, tasas del jugador, reglas y MILP permanecen iguales.

## Datos y barreras temporales

| Fuente | Cobertura usada | Barrera |
| --- | ---: | --- |
| FPL canónico | 2.280 partidos, 2020/21–2025/26 | `as_of(gw)` excluye la GW objetivo |
| Odds históricas | 2.280/2.280 partidos | consenso pre-closing; nunca columnas `C` |
| WhoScored | 291 partidos, 444.252 eventos, hasta GW29 de 2025/26 | una GW completa actualiza únicamente la siguiente |

El consenso 1X2 y over/under se desvigó y se invirtió a dos lambdas Poisson por
mínimos cuadrados acotados. El peso de mercado, **0,95**, se seleccionó solo en
2020/21–2023/24. Las temporadas 2024/25 y 2025/26 quedaron como holdouts completos.

Para eventos, GW10–19 de 2025/26 seleccionó familia y exponente; GW20–29 quedó sin
tocar. La mejor combinación con odds eligió exponente **0,00**, primera señal de que
los agregados de evento no añaden información al mercado.

## Resultados predictivos

### Partido, temporadas holdout

| Temporada | Variante | Devianza Poisson | Brier CS | Log-loss CS | RPS 1X2 |
| --- | --- | ---: | ---: | ---: | ---: |
| 2024/25 | baseline | 1,1227 | 0,1741 | 0,5280 | 0,2051 |
| 2024/25 | odds | **1,0589** | **0,1707** | **0,5182** | **0,1973** |
| 2025/26 | baseline | 1,1268 | 0,1859 | 0,5562 | 0,2138 |
| 2025/26 | odds | **1,0493** | **0,1777** | **0,5341** | **0,2054** |

En el test de eventos GW20–29, el delta odds-minus-baseline fue negativo y su IC95
no cruzó cero tanto en devianza `[-0,1014; -0,0132]` como en Brier CS
`[-0,0152; -0,0027]`. Los eventos solos cruzaron cero en ambas métricas.

### xP de jugador, GW20–38

| Variante | MAE | RMSE | Pearson | Sesgo CS |
| --- | ---: | ---: | ---: | ---: |
| baseline | 0,9459 | 1,8880 | 0,5901 | +8,09% |
| odds-CS | **0,9394** | 1,8819 | 0,5939 | **+2,83%** |
| odds completo | 0,9418 | **1,8778** | **0,5961** | +2,83% |
| eventos | 0,9469 | 1,8897 | 0,5891 | +9,65% |

### Ranking semanal aislado

Se reconstruyó una plantilla válida de 15 desde cero en cada GW. Este control no es
una temporada jugable: elimina transferencias para medir solamente si el ranking de
jugadores mejora.

| Variante | Puntos | Delta | GW ganadas | IC95 del delta |
| --- | ---: | ---: | ---: | ---: |
| baseline | 2.300 | — | — | — |
| odds completo | 2.395 | +95 | 19/38 | [−21; +223] |
| **odds-CS** | **2.387** | **+87** | **24/38** | **[+15; +159]** |
| odds ataque | 2.330 | +30 | 17/38 | [−67; +127] |

La variante defensiva es la única con un intervalo totalmente positivo.

## Por qué no se promueve

El replay que arrastra legalmente la plantilla, en modo nominal y con horizonte 3,
produce:

| Variante | Puntos | Hits | Transferencias | Capitán |
| --- | ---: | ---: | ---: | ---: |
| baseline | **2.168** | 9 | 46 | 264 |
| odds-CS | **2.130** | 13 | 50 | 260 |

El motor de horizonte actual construye jornadas futuras a partir del xP de la GW
actual, ajustado por conteo de fixtures y decay. Esa aproximación era tolerable con
un contexto suave, pero no representa odds específicas de cada partido futuro.
Una señal más aguda cambia rankings y genera una trayectoria distinta de transferencias;
el resultado semanal libre mejora, pero la trayectoria legal aún no.

También se detectó que el replay anonimizado cambia la evaluación del contexto de
equipo: el roster usa alias mientras el histórico conserva nombres. El baseline pasó
de 2.220 anonimizado a 2.168 nominal. Hasta corregir el contrato de alias, las pruebas
de modelos deterministas con fuerza de club deben ejecutarse en modo `named`.

## Siguiente iteración aprobada

1. Generar lambdas y xP por fixture para cada GW del horizonte, usando el snapshot de
   odds disponible antes de la decisión; nunca copiar la proyección actual hacia futuro.
2. Integrar únicamente clean sheets. Mantener ataque y eventos como ablations negativas.
3. Añadir estabilidad: cambiar solo si la ventaja esperada supera coste, incertidumbre y
   valor de guardar la transferencia. No ajustar este umbral sobre el holdout final.
4. Repetir holdouts de partido, xP, ranking semanal y replays legales nominales h=1/h=3.
   La promoción exige no regresión legal y mejoras de calibración sostenidas.
5. Corregir o bloquear el modo anonimizado para cualquier feature que dependa de identidad
   estructural del club.

## Reproducción y evidencia

El runner, tests y evidencia compacta están en `experiments/odds_events/`. Los CSV de
predicciones y traces SQLite se generan fuera de Git. La corrida completa se ejecuta con
el comando del README del experimento. Se verificaron seis tests de causalidad y contrato.

La elección metodológica siguió dos ideas externas: calibrar intensidades contra mercados
1X2 y over/under, y evaluar FPL de forma prospectiva y por horizonte. Football-data además
distingue expresamente odds de apertura y cierre, por lo que las columnas de cierre se
excluyen por construcción.

Fuentes:

- https://www.football-data.co.uk/downloadm.php
- https://arxiv.org/abs/2605.16066
- https://arxiv.org/abs/2508.09992
