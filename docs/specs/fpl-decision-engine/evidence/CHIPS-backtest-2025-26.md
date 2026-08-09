# Evidencia — chips en el backtest ciego de 2025-26

**Fecha:** 2026-08-09 · **Rama:** `feat/fpl-agent-clean` · **Semilla:** 42
**Comando:** `python -m mova_fpl.cli.backtest --season 2025-26 --policy milp --projector points --horizon 3 --chips --lookahead N`

---

## 0. Línea base corregida: 2.217 → 2.220

Al añadir el soporte de wildcard apareció un fallo previo en la linealización de las
transferencias libres. La restricción `ft[t+1] ≤ libres − usadas + hits + 1` es exacta solo
cuando `hits` toma su valor mínimo; el solver podía inflarlo sin coste neto y comprar
transferencias libres futuras que la regla no concede. La cota `ft[t+1] ≤ libres + 1`
—necesaria para el wildcard, que conserva las libres— cierra el agujero.

**Verificado por A/B sobre la temporada completa:**

| Modelo | Puntos |
|---|---:|
| Sin la cota (comportamiento previo) | **2.217** |
| Con la cota (corregido) | **2.220** |

El efecto es pequeño porque el plan de jornadas futuras nunca se ejecuta, solo informa la
decisión de hoy. La línea base del proyecto pasa a **2.220**.

## 1. Resultado

| Configuración | Puntos | vs. base | Chips usados | Caducados |
|---|---:|---:|---:|---:|
| Sin chips (base) | 2.220 | — | 0 | — |
| **Chips, lookahead 3** | **2.303** | **+83** | 8/8 | 0 |
| **Chips, lookahead 6** | **2.303** | **+83** | 8/8 | 0 |
| Chips, lookahead 12 | 2.261 | +41 | 8/8 | 0 |
| Chips, lookahead 20 | 2.277 | +57 | 8/8 | 0 |

Criterio de éxito fijado antes de correr: superar la base; parar y discutir si daba menos de
+40. **Cumplido**: +83 con la configuración por defecto.

Con lookahead 3 y 6 el resultado es idéntico porque en 2025-26 **no hubo ninguna jornada
doble ni en blanco antes de la GW26**: la señal de calendario no ata en la primera vuelta.

## 2. Atribución medida, chip a chip

No es una estimación del modelo. Para cada chip jugado se vuelve a decidir con la
autorización retirada y se puntúa esa decisión contra **los mismos resultados reales**. La
resta es el valor.

### Lookahead 6 (por defecto)

| GW | Chip | Real | Contrafactual | Valor |
|---:|---|---:|---:|---:|
| 2 | wildcard | 65 | 48 | **+17** |
| 3 | bench_boost | 59 | 50 | +9 |
| 4 | triple_captain | 92 | 79 | +13 |
| 15 | free_hit | 68 | 54 | +14 |
| 20 | wildcard | 55 | 62 | **−7** |
| 21 | bench_boost | 66 | 48 | **+18** |
| 22 | triple_captain | 39 | 37 | +2 |
| 24 | free_hit | 90 | 57 | **+33** |
| | | | **suma** | **+99** |

**La suma local (+99) no coincide con la diferencia global (+83).** No es un error: jugar un
chip cambia la trayectoria de la plantilla, y ese efecto de arrastre no lo captura una
comparación jornada a jornada. La cifra que vale es la global.

El wildcard de la GW20 **restó 7 puntos**. Queda registrado: un planificador que solo
reportara sus aciertos no serviría para nada.

## 3. Hallazgo: esperar a la doble jornada fue PEOR

Este es el resultado que no esperaba y que cambia el diseño.

2025-26 tuvo dobles reales en GW26 (2 clubes), **GW33 (6 clubes)** y GW36 (2), y blancos en
GW31 (4 clubes libran) y GW34 (6). Con lookahead 12 y 20 el planificador **sí** ve la GW33 y
reserva el bench boost para ella, que es exactamente lo que recomienda la sabiduría
convencional del juego.

| Chip | Jugado pronto (lookahead 6) | Reservado para la estructura (lookahead 12/20) |
|---|---:|---:|
| bench_boost | GW21: **+18** | GW33: +5 / +8 |
| triple_captain | GW22: +2 | GW34: +5 |
| free_hit | GW24: **+33** | GW38: +2 |

**Por qué.** En una jornada doble el optimizador ya llena el once de jugadores con dos
partidos; los que quedan en el banquillo son precisamente los que **no** doblan. El bench
boost añade poco. Y el contrafactual también es alto: en la GW33 se sacan 75-76 puntos sin
chip alguno.

La lectura general, que vale para el agente que viene:

> **El valor de un chip nace de arreglar una situación mala, no de amplificar una buena.**

El free hit de la GW24 rindió +33 porque la plantilla base rendía 57 esa semana. La GW33 no
necesitaba rescate.

**Cuánta confianza merece esto.** Poca todavía, y por tres razones: es una temporada; el
valor depende de *nuestra* plantilla y *nuestro* modelo, no de una verdad universal; y
contradice la práctica establecida de la comunidad, lo que obliga a más evidencia, no a
menos. Queda como hipótesis a medir con más temporadas (**H-CHIP-02**), no como regla.

**Consecuencia inmediata:** el proxy `structure_factor` para bench boost y triple captain
apunta en la dirección equivocada según esta medición. No se cambia por ahora —ajustar el
diseño a una sola temporada es exactamente el error contra el que existe este backtest— pero
queda declarado.

## 4. Lo que esta evidencia NO demuestra

- **Que jugar los chips temprano sea la estrategia correcta.** Demuestra que en 2025-26, con
  este motor, rindió más. La causa señalada (el banquillo en jornada doble) es plausible y
  consistente con los números, pero no está aislada experimentalmente.
- **Que +83 sea lo que rendirán los chips en 2026/27.** El calendario de dobles y blancos
  será otro.
- **Que el planificador esté bien calibrado.** Los pisos por chip son un punto de partida
  razonado, no medido (**H-CHIP-01**). El wildcard de la GW20 restando 7 puntos sugiere que
  el piso del wildcard está bajo.

## 5. Reproducir

```bash
python -m mova_fpl.cli.backtest --season 2025-26 --policy milp --projector points \
    --horizon 3 --chips --lookahead 6
```

Pruebas asociadas: `tests/test_optimizer_chips.py` (16), `tests/test_chip_planner.py` (13).
La garantía de regresión está en `test_sin_autorizacion_el_modelo_es_el_de_siempre`: sin
chips autorizados no se crea ni una variable y el modelo es idéntico al de v1.
