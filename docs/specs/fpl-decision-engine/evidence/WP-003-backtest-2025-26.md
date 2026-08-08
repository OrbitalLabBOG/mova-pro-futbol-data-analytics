# Backtest 2025-26 · politica `greedy-stub` · modo `anonymized`

run_id `2025-26-greedy-stub-anonymized-7547c758`

| GW | Pts | Acum | Cap | Hits | Subs | Template | Techo |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 35 | 35 | 8 | 0 | 0 | 32 | 152 |
| 2 | 12 | 47 | 2 | 0 | 0 | 44 | 175 |
| 3 | 28 | 75 | 9 | 0 | 0 | 50 | 143 |
| 4 | 46 | 121 | 13 | 0 | 0 | 79 | 149 |
| 5 | 28 | 149 | 9 | 0 | 0 | 49 | 135 |
| 6 | 44 | 193 | 16 | 0 | 0 | 46 | 159 |
| 7 | 31 | 224 | 8 | 0 | 0 | 64 | 151 |
| 8 | 38 | 262 | 13 | 0 | 0 | 70 | 169 |
| 9 | 14 | 276 | 2 | 0 | 0 | 58 | 169 |
| 10 | 39 | 315 | 13 | 0 | 0 | 70 | 141 |
| 11 | 16 | 331 | 4 | 0 | 0 | 31 | 153 |
| 12 | 14 | 345 | 2 | 0 | 0 | 22 | 173 |
| 13 | 12 | 357 | 2 | 0 | 0 | 24 | 159 |
| 14 | 49 | 406 | 14 | 0 | 0 | 62 | 167 |
| 15 | 11 | 417 | 2 | 0 | 0 | 40 | 159 |
| 16 | 61 | 478 | 13 | 0 | 0 | 72 | 174 |
| 17 | 60 | 538 | 16 | 0 | 0 | 70 | 165 |
| 18 | 26 | 564 | 2 | 0 | 0 | 50 | 158 |
| 19 | 38 | 602 | 2 | 0 | 0 | 40 | 144 |
| 20 | 21 | 623 | 2 | 0 | 0 | 28 | 157 |
| 21 | 22 | 645 | 6 | 0 | 0 | 59 | 145 |
| 22 | 24 | 669 | 2 | 0 | 0 | 36 | 125 |
| 23 | 26 | 695 | 1 | 0 | 0 | 58 | 138 |
| 24 | 39 | 734 | 5 | 0 | 0 | 64 | 146 |
| 25 | 55 | 789 | 11 | 0 | 0 | 79 | 152 |
| 26 | 43 | 832 | 5 | 0 | 0 | 71 | 164 |
| 27 | 28 | 860 | 6 | 0 | 0 | 40 | 157 |
| 28 | 11 | 871 | 0 | 0 | 0 | 59 | 147 |
| 29 | 38 | 909 | 2 | 0 | 0 | 64 | 158 |
| 30 | 17 | 926 | 2 | 0 | 0 | 53 | 128 |
| 31 | 15 | 941 | 2 | 0 | 0 | 46 | 145 |
| 32 | 50 | 991 | 4 | 0 | 0 | 60 | 180 |
| 33 | 49 | 1040 | 6 | 0 | 0 | 65 | 187 |
| 34 | 39 | 1079 | 5 | 0 | 0 | 57 | 136 |
| 35 | 52 | 1131 | 4 | 0 | 0 | 53 | 153 |
| 36 | 43 | 1174 | 3 | 0 | 1 | 84 | 154 |
| 37 | 58 | 1232 | 7 | 0 | 0 | 65 | 154 |
| 38 | 70 | 1302 | 14 | 0 | 0 | 29 | 150 |

## Resultado frente a baselines

| Serie | Puntos | vs motor |
|---|---:|---:|
| **Motor (greedy-stub)** | **1302** | — |
| template | 2043 | -741 |
| random | 533 | +769 |
| ceiling | 5871 | -4569 |

Captura del techo con informacion perfecta: **22.2%**

## Criterios

| Criterio | Resultado | Evidencia |
|---|---|---|
| AC-WP003-001 | **pass** | 38 jornadas completadas |
| AC-WP003-002 | **pass** | Instrumentación `as_of` activa en toda la corrida |
| AC-WP003-003 | **pass** | GW1 resuelta con `train_rows=0` |
| AC-WP003-004 | **pass** | template · random · ceiling, ninguno en cero |
| AC-WP003-005 | **pass** | `test_misma_entrada_misma_decision` |
| AC-WP003-006 | **pass** | `test_reproducibilidad_con_la_misma_semilla` |
| AC-WP003-007 | **pass** | `vs_baseline()` responde sin recomputar |
| AC-WP003-008 | **pass** | `test_reanudacion_no_recomputa` |

## Bugs encontrados y corregidos durante la ejecución

| # | Síntoma | Causa raíz |
|---|---|---|
| 1 | GW1 sacaba 1 punto | Prior plano por posición dejaba el xp casi constante; el desempate por precio ascendente armaba el equipo de los 15 más baratos del juego. El precio correlaciona 0,32 con los puntos y estaba sin usar |
| 2 | `template` = 0 en 10 de 38 jornadas | Aritmética en float: `95.8 + 4.2 = 100.00000000000001` superaba el presupuesto y la plantilla quedaba en 14/15. FPL opera en décimas enteras |
| 3 | `ninguna formacion valida` a mitad de temporada | Los jugadores en **jornada en blanco** no tienen fila y se borraban de la plantilla, que se encogía hasta ser inválida |
| 4 | `SquadInfeasible` en toda corrida | El lookahead de coste recorría los candidatos en orden de xp en vez de por precio: estimaba 127M donde la plantilla más barata costaba 64M |
| 5 | El lookahead ignoraba la cuota de 3 por club | Aceptaba caros creyendo poder cerrar con un suplente barato bloqueado por club |
