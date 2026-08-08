# WP-005 · Evidencia — AC-WP005-005: el motor con este modelo supera al template

**Fecha:** 2026-08-08 · **Temporada:** 2025-26 · **Modo:** `anonymized` · **Semilla:** 42

```bash
python -m mova_fpl.cli.train_points --holdout 2025-26
python -m mova_fpl.cli.backtest --season 2025-26 --policy milp --projector points --horizon 3 --seed 42
```

## Resultado

| Proyector | Política | Puntos | vs `template` (2.043) | Captura del techo |
|---|---|---:|---:|---:|
| `naive` (WP-003) | greedy | 1.302 | −741 | 22,2% |
| `minutes` (WP-004) | greedy | 1.298 | −745 | 22,1% |
| **`points` (WP-005)** | greedy | 1.333 | −710 | 22,7% |
| `minutes` | milp h=1 | 2.014 | −29 | 34,3% |
| **`points`** | milp h=1 | **2.178** | **+135** | 37,1% |
| `minutes` | milp h=3 | 2.010 | −33 | 34,2% |
| **`points`** | **milp h=3** | **2.217** | **+174** | **37,8%** |
| `minutes` | milp h=5 | 2.131 | +88 | 36,3% |
| **`points`** | milp h=5 | 2.207 | +164 | 37,6% |

**AC-WP005-005 cumplido.** El motor con el modelo descompuesto supera al baseline
`template` en las tres configuraciones del optimizador, con un margen de entre +135 y +174.

## Cuánto aporta el modelo, y bajo qué política

Con la misma política, cambiar el proyector de `minutes` a `points` vale:

| Política | minutes | points | Ganancia |
|---|---:|---:|---:|
| greedy | 1.298 | 1.333 | **+35** |
| milp h=1 | 2.014 | 2.178 | **+164** |
| milp h=3 | 2.010 | 2.217 | **+207** |
| milp h=5 | 2.131 | 2.207 | **+76** |

El dato interesante no es la magnitud, es la dependencia: **una proyección mejor casi no
sirve bajo una política que no actúa sobre ella.** La voraz hace nueve transferencias en la
temporada, así que da igual lo bien que estén ordenados los jugadores que nunca va a fichar:
gana 35 puntos. El optimizador, que hace cincuenta, convierte la misma mejora en 207.

Es la contracara exacta del diagnóstico de WP-004, donde una política pobre hacía invisible
al modelo. Modelo y política no se suman, se multiplican.

## El techo sigue lejos, y ahora se sabe por qué

Capturamos el **37,8%** de los 5.871 puntos que daría la información perfecta. Esa distancia
ya no se puede atribuir ni al optimizador —su brecha de optimalidad medida es 0,000%— ni al
sesgo agregado del modelo, que es **−0,4%** sobre 15.163 proyecciones.

Lo que queda es varianza irreducible más la parte del error que no es sesgo. Un modelo
insesgado puede seguir siendo poco informativo, y la correlación por jugador-jornada
(0,60 en la GW20) dice cuánto: bastante, pero no lo suficiente para acertar el once ideal.
Cerrar más exige información que el almacén no tiene — alineaciones probables, lesiones,
rotación anunciada— y eso es agente, no modelo.

## Q-05 se refuerza: el horizonte óptimo no es estable

Con el proyector de minutos el mejor horizonte era 5 (2.131) y h=3 quedaba último (2.010).
Con el proyector de puntos el mejor es **3** (2.217) y h=5 baja al segundo puesto (2.207).

El orden se invirtió al cambiar una pieza distinta del sistema. Eso es exactamente lo que
se espera de diferencias que están dentro del ruido de una sola temporada, y confirma que
fijar N por el resultado de un backtest sería sobreajustar. Queda pendiente de decidir con
más temporadas o con validación cruzada temporal.

## Corridas

| `run_id` | Configuración | Puntos |
|---|---|---:|
| `wp005-greedy-stub-h1` | greedy · points | 1.333 |
| `wp005-milp-h1` | milp h=1 · points | 2.178 |
| `wp005-milp-h3` | milp h=3 · points | 2.217 |
| `wp005-milp-h5` | milp h=5 · points | 2.207 |
