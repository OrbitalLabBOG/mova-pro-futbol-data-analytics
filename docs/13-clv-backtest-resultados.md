# Backtest de CLV — ¿se puede ganar consistentemente? (resultado empírico)

> **Ejecutado:** 2026-06-29 · `scripts/clv_backtest.py` sobre `data/betting.db`.
> **Muestra:** **80.815 partidos** de clubes con apertura **y** cierre de Pinnacle (24 ligas, 1996-2026), leakage-free.
> **Modelo:** Elo de clubes walk-forward (K=20, HFA=65) + calibración 1X2 (logit multinomial, ventana expansiva re-ajustada por año → **sin fuga de información**). Independiente del mercado.

## Pregunta
¿Nuestro modelo le gana al **cierre de Pinnacle** (el precio más sharp) de forma consistente? Si sí → edge real explotable. Si no → los mercados son eficientes y apostar direccional es −EV (como predice la teoría).

## Resultados

### Test 1 · Skill predictivo (RPS, menor = mejor)
| Predictor | RPS |
|---|---|
| **Cierre Pinnacle** | **0.2015** ← benchmark sharp |
| Apertura Pinnacle | 0.2025 |
| **Modelo (Elo+logit)** | **0.2084** |

El modelo es **peor que el cierre por +15.9 errores estándar** (Δ=+0.0069, SE≈0.0004). Estadísticamente aplastante: **el modelo NO le gana al cierre** — ni a la apertura. (El gap es pequeño en magnitud, pero perfectamente consistente: el mercado predice mejor.)

### Test 2 · Value betting vs apertura + CLV (el test clave)
Apostar 1 unidad a la apertura de Pinnacle cuando el modelo ve EV>umbral; medir CLV (vs cierre justo) y ROI realizado.

| Umbral EV | # apuestas | CLV medio | %CLV>0 | ROI | t-stat |
|---|---|---|---|---|---|
| 0% | 103.062 | **−2.97%** | 31.2% | **−5.74%** | −11.05 |
| 2% | 90.319 | −2.99% | 31.6% | −6.06% | −10.79 |
| 5% | 73.573 | −3.02% | 32.1% | −6.59% | −10.37 |
| 10% | 51.907 | −3.05% | 32.9% | **−7.48%** | −9.57 |

- **CLV negativo y consistente (≈−3%):** sistemáticamente tomamos **peores** precios que el cierre. Solo ~31% de las apuestas batieron el cierre (lo esperable sin edge es ~50%).
- **ROI fuertemente negativo (−5.7% a −7.5%), t≈−10/−11:** no es ruido, es una pérdida estructural significativa.
- **Cuanto más exigente el umbral, PEOR el ROI.** Esta es la prueba de fuego: si tuviéramos edge, ser más selectivo mejoraría el ROI. Que empeore demuestra que el "valor" que ve el modelo es **su propio error vs un mercado más sharp** (auto-selección adversa).

### Test 3 · Calibración del cierre (validación teórica)
| Prob. cierre | Frecuencia real | n |
|---|---|---|
| ~7.2% | 5.7% | 6.192 |
| ~15.9% | 15.2% | 27.841 |
| ~26.1% | 25.7% | 91.797 |
| ~33.9% | 34.0% | 53.571 |
| ~44.6% | 45.1% | 29.977 |
| ~54.6% | 55.2% | 17.380 |
| ~64.4% | 65.4% | 8.889 |
| ~74.4% | 77.9% | 4.668 |
| ~83.9% | 86.0% | 1.994 |
| ~91.5% | 96.3% | 136 |

**Error de calibración medio: 0.0049 (≈ perfecto).** El cierre de Pinnacle es casi exactamente la probabilidad verdadera. *Esta es la razón de fondo por la que no se le puede ganar:* el precio ya ES la verdad. (Único matiz: leve subestimación de favoritos extremos — favorite-longshot bias — pero con muestra ínfima.)

### Test 4 · Batir el cierre directo (edge puro)
Apostar al **cierre** cuando el modelo discrepa: ROI **−5.81%** (umbral 0%) y **−6.55%** (umbral 5%), t≈−11. Confirmado: batir el cierre con un modelo simple es imposible.

## Veredicto

**No se puede ganar consistentemente apostando direccional (1X2/resultado) en estos mercados** — empíricamente demostrado sobre 80K partidos con datos de calidad, y **la teoría queda validada**: el cierre de Pinnacle está casi perfectamente calibrado (es la "verdad" de mercado), por lo que el techo de *cualquier* modelo es **igualar** el cierre, no batirlo; y para ganar plata hay que batirlo por **más que el vig**. Nuestro modelo ni lo iguala.

Notas honestas:
- Es un modelo competente pero **simple** (Elo+logit). Modelos pro más sofisticados podrían *acercarse* más al cierre, pero el Test 3 muestra que **no hay margen**: el cierre ya es la verdad. Acercarse ≠ batir.
- Esto es **fútbol de clubes con datos ricos**. El Mundial (menos datos, más varianza, 48 equipos) sería **más difícil**, no más fácil.
- **Qué NO refuta esto:** el edge **estructural** de Polymarket (market making, arbitraje, resolution-edge) — que NO depende de predecir mejor — sigue en pie. Ver [docs/12 §4](12-estrategia-apuestas-investigacion.md). Este backtest cierra la puerta a "out-predecir al mercado"; no a la microestructura.
- **Para la polla** (sin vig, contra humanos sesgados) el modelo sigue siendo útil: valor/ownership/camino de bracket. Ese es el juego ganable de este repo.

## Reproducir
```bash
python scripts/collect_club_odds.py   # carga el mirror → data/betting.db (idempotente)
python scripts/clv_backtest.py        # corre los 4 tests (~34s)
```
Datos: `git clone --depth 1 https://github.com/huhao930422-debug/football-odds-mirror.git data/club-odds-mirror`
