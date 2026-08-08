# WP-005 · Evidencia — la descomposición es coherente

**Fecha:** 2026-08-08 · **Suite:** 509 pruebas verdes + 2 marcadas `slow`

```bash
pytest tests/test_points_decomposition.py tests/test_defcon_calibration.py -v
pytest -m slow tests/test_defcon_calibration.py
```

## AC-WP005-001 — la suma de componentes es el total

| Prueba | Qué afirma |
|---|---|
| `test_la_suma_de_componentes_es_el_total` | Sobre un catálogo sintético, `Σ componentes == xp` con tolerancia 1e-9 |
| `test_la_suma_cuadra_tambien_con_datos_reales` | Sobre las 812 filas del catálogo real de la GW20, tolerancia 1e-6 |

La identidad no es casual: `xp` **se calcula** sumando las columnas de componente. La prueba
existe para que siga siendo así — el día que alguien añada un componente y olvide sumarlo,
o calcule el total por otra vía, la prueba lo detecta.

## AC-WP005-002 — `project()` devuelve el desglose

`test_project_devuelve_el_desglose_no_solo_el_total` verifica las diez columnas de
componente más cinco de diagnóstico: `p_juega`, `p_60`, `p_porteria_cero`, `p_defcon`,
`lambda_encajados`.

Es lo que permite que una decisión se explique: *"capitán X porque P(60+) = 0,95 y
xG90 = 0,7"*, en vez de *"capitán X porque el modelo dijo 8,4"*. Precondición para que el
agente LLM de v2 pueda cuestionar al modelo con evidencia, y no solo obedecerlo.

## AC-WP005-007 — cada fila reporta su incertidumbre

| Prueba | Qué afirma |
|---|---|
| `test_cada_fila_reporta_incertidumbre` | `xp_sd >= 0` siempre, y `> 0` para quien puede jugar |
| `test_la_incertidumbre_crece_cuando_no_se_sabe_si_juega` | Un rotativo 50/50 tiene mayor `xp_sd` relativa que un fijo |

La varianza total incluye el **término de mezcla** entre ramas:

```
Var = Σ_rama  P(rama) · (Var_rama + μ_rama²)  −  xP²
```

Para un titular fijo domina la varianza interna (¿marcará?). Para un suplente domina la
mezcla (¿jugará?). Sin ese término, el optimizador no distingue entre tres puntos seguros y
tres puntos que salen de una moneda — y esa distinción es la que hace falta el día que se
active la función objetivo de mini-liga (ADR-007).

## Las reglas se aplican dentro de cada rama, no sobre el promedio

Ésta es la decisión de diseño que más cambia los números, y tiene cinco pruebas:

| Prueba | Regla de FPL que protege |
|---|---|
| `test_la_porteria_a_cero_solo_puntua_en_la_rama_de_60` | La portería a cero exige 60 minutos |
| `test_los_puntos_de_aparicion_son_uno_o_dos_nunca_intermedios` | 1 o 2 puntos, jamás 1,4 |
| `test_el_portero_no_recibe_puntos_de_contribucion_defensiva` | GKP no es elegible para DefCon |
| `test_solo_portero_y_defensa_pagan_los_goles_encajados` | La penalización es posicional |
| `test_quien_no_juega_no_puntua` | Con P(0 min) = 1, el xP y su sd son exactamente 0 |

Promediar primero y aplicar reglas después produce números que ninguna rama puede generar.
Por eso el modelo evalúa la rama parcial y la completa por separado y las mezcla al final.

## Dos redondeos que no son divisiones

FPL redondea **hacia abajo** en dos sitios: −1 por cada 2 goles encajados y +1 por cada 3
paradas. Dividir la media por el divisor sobreestima ambos, porque el resto se pierde en
cada partido y no se acumula entre jornadas.

```
E[floor(X/2)] con X ~ Poisson(1)  =  0,2838        λ/2  =  0,50
```

`esperanza_division` suma la masa de la Poisson y da el valor exacto.
`test_la_penalizacion_por_goles_no_es_la_mitad_de_la_media` fija el número.

El error estaba activo en el componente de paradas hasta que la evaluación por componente
lo delató: **+43,5% de sesgo**, que bajó a −12,1% al usar la esperanza exacta.

## AC-WP005-004 — calibración de la contribución defensiva

Ocho pruebas de propiedades (monotonía en la tasa, monotonía en los minutos, umbral por
posición, portero excluido, dispersión en rango, cola más gruesa que Poisson) más una
`slow` sobre la ventana real GW20-38 de 2025-26.

**ECE = 0,0110** frente a un umbral de 0,08. Detalle por posición y curva de calibración en
`WP-005-componentes.md`.

Una propiedad merece mención aparte:
`test_sin_la_columna_el_modelo_lo_declara_en_vez_de_inventar`. La regla de DefCon no existía
antes de 2025/26, así que en el backtest ciego de esa temporada el modelo se entrena sin un
solo dato del componente. En vez de rellenar con ceros —que sería afirmar que nadie hacía
acciones defensivas— el modelo marca `sin_datos = True`, usa una dispersión declarada por
defecto y la reestima con lo que va llevando la temporada en curso.

Para 2026/27 esa limitación desaparece: habrá una temporada completa de la regla vigente.
