# WP-006 · Evidencia — la solución del optimizador es legal

**Fecha:** 2026-08-07 · **Rama:** `feat/fpl-agent-clean` · **Suite:** 439 pruebas verdes

```bash
pytest tests/test_optimizer_constraints.py tests/test_optimizer_horizon.py -v
pytest -m slow tests/test_optimizer_constraints.py::test_temporada_completa_sin_una_sola_violacion
```

## AC-WP006-001 — nunca viola `validate_squad`

| Prueba | Qué afirma |
|---|---|
| `test_la_solucion_pasa_validate_squad` | El `Squad` reconstruido de la solución devuelve **cero** violaciones |
| `test_composicion_exacta_2_5_5_3` | La composición es exacta, no "al menos" |
| `test_maximo_tres_por_club_aunque_ahi_esten_los_mejores` | Con los cinco mejores jugadores concentrados en un club, el modelo deja puntos sobre la mesa antes que violar la cuota |
| `test_formacion_valida_y_un_solo_capitan` | XI de 11, exactamente un portero, capitán titular |
| `test_temporada_completa_sin_una_sola_violacion` *(slow)* | Las 38 jornadas reales de 2025-26 con `horizon=3` |

La prueba de club está construida al revés a propósito: se **inflan** en +50 xp los jugadores
de un mismo club para que la restricción sea la única razón por la que el modelo no los
ficha a todos. Si la cuota se relajara, la prueba lo detecta; una prueba con un mercado
neutro no lo haría.

## AC-WP006-003 — presupuesto real, no £100M fijos

| Prueba | Qué afirma |
|---|---|
| `test_arranque_en_frio_respeta_el_presupuesto_de_100m` | En GW1 el tope sí es 100M y el banco cuadra con el coste |
| `test_con_plantilla_el_tope_es_banco_mas_valor_no_100m` | Con plantilla vigente el tope es **valor de venta + banco**, no el nominal |
| `test_el_precio_de_venta_no_devuelve_toda_la_subida` | Comprado a 5.0 y valorado en 6.0, la venta aporta 5.5 |

La restricción de caja está escrita como conservación, no como tope:

```
banco[t] = banco[t-1] + Σ venta_i · vende[i,t] − Σ precio_i · compra[i,t]  ≥ 0
```

Con `venta_i = selling_price(compra, actual)` en la jornada que se decide. Es la razón por
la que un modelo con £95M de plantilla y £0.5M en banco no puede fichar a un jugador de
£10M vendiendo a uno de £4M, aunque £100M "cabrían".

## AC-WP006-004 — transferencias libres y hits

| Prueba | Qué afirma |
|---|---|
| `test_una_transferencia_libre_no_cuesta_hit` | Una transferencia con una libre disponible cuesta 0 |
| `test_la_segunda_transferencia_cuesta_cuatro_puntos` | `hits == max(0, compras − libres)`, verificado hundiendo a dos titulares a xp negativo |
| `test_las_libres_se_acumulan_hasta_el_tope_en_el_horizonte` | Con 5 libres no hay hits y nunca se superan las 5 |
| `test_el_tope_de_hits_por_jornada_se_respeta` | Con seis titulares hundidos, el modelo se detiene en el tope configurado |

La acumulación de libres es una recurrencia entera y se linealiza así:

```
libres[t+1] ≤ (libres[t] − usadas[t] + hits[t]) + 1        libres[t+1] ∈ [1, 5]
```

En el óptimo `hits[t]` toma su cota inferior porque está penalizado, de modo que el
paréntesis vale exactamente `max(0, libres − usadas)`. Queda la duda razonable de si el
solver podría **inflar** `hits[t]` para comprarse una transferencia libre futura: cuesta
cuatro puntos y ahorra como mucho cuatro, así que nunca es estrictamente mejor. La
equivalencia se sostiene sin big-M.

## AC-WP006-005 — infactible falla ruidosamente

| Prueba | Mensaje verificado |
|---|---|
| `test_sin_porteros_suficientes_falla_nombrando_la_posicion` | `solo 1 GKP en el mercado, hacen falta 2` |
| `test_sin_presupuesto_falla_diciendo_cuanto_falta` | `la plantilla más barata cuesta 300.0M y el presupuesto disponible es 100.0M` |
| `test_con_pocos_clubes_falla_por_la_cuota` | `con máximo 3 por club no se llegan a 15 jugadores: solo hay 4 clubes` |
| `test_nunca_devuelve_una_plantilla_incompleta` | Con exactamente 15 jugadores disponibles devuelve 15, no 14 |

`Infeasible` lleva la lista completa de motivos, no el primero: al depurar hace falta el
cuadro entero. El diagnóstico corre **antes** del solver cuando la causa es estructural, así
que el error es inmediato y legible en vez de un `Status: Infeasible` sin explicación.
