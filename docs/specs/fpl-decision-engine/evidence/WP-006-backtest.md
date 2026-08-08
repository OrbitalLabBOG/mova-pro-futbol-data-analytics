# WP-006 · Evidencia — AC-WP006-007: el optimizador mejora el resultado

**Fecha:** 2026-08-07 · **Rama:** `feat/fpl-agent-clean`

## Comparación contra el estado anterior

WP-005 (modelo de puntos por componentes) todavía no existe: WP-006 se adelantó porque el
diagnóstico de WP-004 mostró que su retorno esperado era seis veces mayor. La referencia
válida es entonces **el mejor resultado del proyecto hasta esta iteración**: la política
voraz con el proyector de minutos de WP-004.

```bash
python -m mova_fpl.cli.backtest --season 2025-26 --policy greedy-stub --projector minutes --horizon 1 --seed 42
python -m mova_fpl.cli.backtest --season 2025-26 --policy milp        --projector minutes --horizon 5 --seed 42
```

| | greedy-stub h=1 | milp h=1 | milp h=5 |
|---|---:|---:|---:|
| Puntos de temporada | 1,298 | 2,014 | **2,131** |
| Puntos por jornada | 34.2 | 53.0 | **56.1** |
| Captura del techo | 22.1% | 34.3% | **36.3%** |
| vs `template` (2,043) | −745 | −29 | **+88** |
| Transferencias | 9 | 48 | 52 |
| Hits pagados | 0 | 11 | 15 |
| `run_id` | `wp006-greedy-stub-h1` | `wp006-milp-h1` | `wp006-milp-h5` |

**AC-WP006-007 cumplido con margen.** Con el mismo proyector y la misma información, cambiar
solamente la política suma **+716 puntos** (+55%).

## Por qué la voraz perdía tanto

El detalle revelador es la fila de transferencias: la voraz hizo **nueve en toda la
temporada**. No porque las ahorrara, sino porque su regla —"una transferencia si mejora el
xp del XI más allá del coste del hit"— casi nunca se activaba: comparaba el mejor fichaje
posible contra el peor jugador de la plantilla, uno a uno, y evaluaba solo el efecto
inmediato sobre el XI. Con 52 transferencias en la misma temporada, el MILP mantiene la
plantilla viva.

La segunda pérdida era estructural. La voraz construye la plantilla **una sola vez**, en la
GW1, y después la parcha. El MILP la reconsidera entera en cada jornada sujeta al
presupuesto y a las transferencias disponibles; cuando la reconstrucción completa no cabe,
el modelo elige la mejor secuencia parcial que sí cabe. Es la diferencia entre reparar y
replanificar.

## Lo que sigue sin estar resuelto

El techo con información perfecta es **5,871**. Capturamos el 36.3%. La distancia no es
del optimizador: dado un xp, el MILP encuentra la mejor plantilla posible —está probado en
`WP-006-prefiltro.md` que la brecha de optimalidad es 0.000% en cinco de seis jornadas
medidas—. Lo que falta ahora es **la calidad del xp**, y eso es WP-005.

Es la inversión exacta del diagnóstico anterior. En WP-004 la brecha de política (−633) era
seis veces la de proyección (−108); hoy la de política está cerrada y lo que queda es
proyección. El siguiente punto de mayor retorno vuelve a ser el modelo.

## Cambios colaterales que afectan a los números

Dos correcciones entraron con este workpack y mueven también el baseline. Se declaran para
que la comparación con corridas anteriores sea legible:

1. **Transferencia libre del arranque.** El simulador daba **dos** transferencias libres en
   la GW2 (`accumulate_free_transfers(1, 0, 5) = 2`). FPL da una: la plantilla inicial no
   consume ninguna pero tampoco acumula. Corregido; endurece a todas las políticas por igual.

2. **Alias de club inestable en modo anónimo.** El mapa `club → CLUB_nn` se construía con los
   equipos presentes en cada jornada. En una jornada en blanco faltan clubes, los índices se
   corren y `CLUB_03` deja de ser el mismo equipo entre jornadas — con la cuota de tres por
   club evaluándose contra etiquetas inconsistentes. Ahora el mapa se construye una vez por
   temporada. Cubierto por `test_el_alias_de_club_es_estable_en_toda_la_temporada`.

La corrida `wp006-greedy-stub-h1` (1,298) se relanzó con ambas correcciones aplicadas, así
que la comparación de esta página es limpia. Coincide con el 1,298 de WP-004 por casualidad
aritmética: la voraz hizo tan pocas transferencias que la libre extra nunca llegó a usarse.
