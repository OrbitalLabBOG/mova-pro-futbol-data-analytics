# WP-006 · Evidencia — la ganancia del horizonte está medida, no supuesta

**Fecha:** 2026-08-07 · **Temporada:** 2025-26 · **Modo:** `anonymized` · **Proyector:** `minutes` · **Semilla:** 42

## AC-WP006-002 — con horizonte 3, el xP acumulado no es peor

Se verifica sobre un mercado sintético construido para que el horizonte **importe**: los
jugadores de un club valen 0.1 en las dos primeras jornadas y 12.0 en la tercera. Ambas
políticas resuelven con la misma matriz de xp y se comparan sobre el mismo tramo.

| Solver | xP acumulado GW10-12 | Estrellas en plantilla | Transferencias GW12 | Hits |
|---|---:|---|---:|---:|
| horizonte 3 | **141.2** | GW10: 1 · GW11: 1 · GW12: 3 | 2 | 0 |
| horizonte 1 | 137.2 | GW10: 0 · GW11: 0 · GW12: 3 | 3 | 1 |

El mecanismo es exactamente el que se buscaba: el solver con horizonte **compra una estrella
tres jornadas antes de que puntúe**, pagando xp que no necesita, para llegar a la jornada
grande sin tener que pagar un hit. El miope no puede: cada semana toma la mejor decisión de
esa semana.

La prueba `test_horizonte_3_no_es_peor_que_horizonte_1_sobre_el_mismo_tramo` afirma
`largo > corto`, no `>=`. Con `>=` el test seguiría verde si el horizonte dejara de influir
y nadie se enteraría.

## Resultado sobre la temporada real

Cinco corridas completas de 38 jornadas, idénticas salvo el horizonte:

| Política | Horizonte | Puntos | vs greedy | vs template | Transf. | Hits | Captura del techo |
|---|---:|---:|---:|---:|---:|---:|---:|
| `greedy-stub` | 1 | 1,298 | — | −745 | 9 | 0 | 22.1% |
| `milp` | 1 | 2,014 | **+716** | −29 | 48 | 11 | 34.3% |
| `milp` | 3 | 2,010 | +712 | −33 | 52 | 15 | 34.2% |
| `milp` | **5** | **2,131** | **+833** | **+88** | 52 | 15 | **36.3%** |
| `milp` | 8 | 2,080 | +782 | +37 | 53 | 16 | 35.4% |

Referencias fijas de la temporada: `template` 2,043 · `random` 533 · `ceiling` 5,871.

### Lo que estos números dicen, y lo que no

**Sí dicen** que el diagnóstico de WP-004 era correcto. Allí se midió una brecha de política
de −633 puntos y una de proyección de −108, y se concluyó que el optimizador valía seis
veces más que mejorar los modelos. El optimizador aportó **+716 puntos con horizonte 1**, es
decir, con la misma información que ya tenía la voraz. La brecha era de política, y era esa.

**Sí dicen** que con horizonte 5 el motor supera por primera vez al baseline `template`
(+88). Hasta ahora ninguna configuración del proyecto había ganado a "copiar a la multitud".

**No dicen** que más horizonte sea siempre mejor. El resultado **no es monótono**: h=3 (2,010)
queda por debajo de h=1 (2,014), y h=8 (2,080) por debajo de h=5 (2,131). La monotonía que sí
se cumple es la del AC-WP006-002 —sobre *xP proyectado* y el *mismo tramo*— y ésa es una
identidad matemática. Sobre *puntos realizados* de una temporada, un horizonte largo
optimiza con más fuerza contra proyecciones que se degradan con la distancia: el modelo se
compromete con un futuro que su propio proyector no acierta. Con h=8 la GW+7 pesa
`0.84⁷ = 0.30` y sigue moviendo decisiones de hoy.

**Con una sola temporada de 38 jornadas, la diferencia entre 2,014 y 2,131 no es
estadísticamente separable de la suerte.** Elegir h=5 porque ganó esta corrida es
sobreajustar al backtest. La lectura defendible es: *el horizonte largo ayuda; el valor
concreto de N necesita más temporadas o una validación cruzada temporal antes de fijarse*.
Queda como pregunta abierta Q-05.

## Dobles jornadas y jornadas en blanco

2025-26 tiene tres jornadas dobles (26, 33, 36 — diez pares equipo-jornada) y dos en blanco
(31 con 16 equipos, 34 con 14). Son las jornadas donde el calendario decide el resultado:

| GW | Tipo | greedy | milp h=1 | milp h=5 |
|---:|---|---:|---:|---:|
| 26 | doble | 41 | 62 | 70 |
| 31 | blanca | 29 | 47 | 55 |
| 33 | doble | 41 | 67 | 66 |
| 34 | blanca | 29 | 32 | 44 |
| 36 | doble | 67 | 89 | 79 |

La voraz nunca supo que existían: su proyector entrega una fila por jugador y trata una
doble jornada como una sencilla. `build_xp_matrix` multiplica el xp por el número real de
partidos de ese club en esa jornada, de modo que una doble vale el doble y una blanca vale
cero. Parte de la ventaja de `milp h=1` sobre la voraz viene de ahí y no del solver — son
cinco jornadas de 38, así que explica una fracción menor del +716, pero es honesto decir que
las dos mejoras viajaron juntas en el mismo cambio.

## Limitación declarada — L-01

El calendario se lee del almacén ya ingerido, así que incorpora **reprogramaciones que en su
momento podían no estar anunciadas**. Un manager de la GW20 de 2025-26 quizá no sabía todavía
que la GW34 quedaría en blanco para seis equipos. Es un adelanto de información real, acotado
a las jornadas reprogramadas, y no se ha medido su efecto por separado. Está registrado en
`mova_fpl/optimizer/horizon.py` y en `Store.team_schedule`. Corregirlo exige una instantánea
histórica del calendario tal como se publicó, que el almacén hoy no tiene.
