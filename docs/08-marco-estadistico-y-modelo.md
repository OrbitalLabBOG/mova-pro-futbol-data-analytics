# Marco estadístico y diseño del modelo ganador

> Síntesis de investigación profunda (2026-06-28, 4 frentes + sub-investigaciones). Todas las fuentes convergen en una arquitectura clara. Este doc define **qué construir y por qué**, aterrizado a nuestros datos. Es el plano de la Fase 2.

---

## 0. Las 5 verdades que la evidencia deja claras

1. **El mercado es el rival a vencer, no un detalle.** El *Bookmaker Consensus Model* (Leitner-Zeileis-Hornik 2010) **supera a Elo y al ranking FIFA**. Un modelo puro que ignora el mercado **pierde**: el SPI de FiveThirtyEight, famoso y bien hecho, dio **−6.2% ROI** en 36K partidos porque estaba mal calibrado ("acierta la dirección, falla la confianza"). → **Anclar al mercado, el modelo es la corrección.**
2. **Lo mejor publicado es híbrido.** Groll et al. (2019): un random forest que combina **Poisson bivariado + consenso de mercado + valor de plantilla + ratings de jugador** bate incluso a las propias odds. El ganador no es "modelo vs mercado", es **mercado COMO feature + señal propia**.
3. **El Elo-diff domina** en selecciones (~100× más influyente que la siguiente variable; arXiv 2606.24171). Con pocos partidos por equipo, "la elección de modelo casi no mueve la aguja" — lo que mueve es la **fuerza relativa bien estimada**.
4. **xG > goles** para estimar fuerza (regresión a la media de la suerte de finalización). **Construir nuestro propio xG** desde coordenadas WhoScored, entrenado en StatsBomb, es **nuestra ventaja diferencial** sobre la polla.
5. **Ganar la polla ≠ calibrar bien.** P(quedar 1º) se maximiza con **leverage y contrarianismo** (en pools grandes), no maximizando aciertos. El dato más valioso = `P_modelo / ownership_público`.

---

## 1. Arquitectura del modelo (capas)

```
                          ┌─────────────────────────────────────┐
 FUERZA      Elo-diff (+trayectoria 6m)  ──►  prior dominante    │
            xGF/xGA por equipo (de NUESTRO xG)  ──► ataque/defensa│
                          └───────────────┬─────────────────────┘
                                          ▼
 MOTOR DE PARTIDO   Elo+xG → goles esperados (λ) → Dixon-Coles
                    (Poisson bivariado + corrección ρ marcadores bajos
                     + time-decay ξ)  →  P(1X2) por partido
                                          ▼
 BLEND          log-opinion pool:  p ∝ p_modelo^(1-w) · p_mercado^(w)
                w≈0.75-0.85 (mercado devigueado con Power/Shin)
                                          ▼
 TORNEO         Monte Carlo 100K del bracket (R32→Final)
                ET a ⅓ fuerza · penales ~55-57% al favorito
                → P(avance/campeón) por equipo
                                          ▼
 DECISIÓN POLLA  Leverage = P_modelo / ownership  → picks que
                 maximizan P(quedar 1º) simulando contra el campo
```

## 2. Modelo de partido — Elo→Dixon-Coles sobre xG

**Por qué este y no otro:** Dixon-Coles (1997) es el estándar de oro práctico (~56-58% acierto 1X2). Sobre Poisson independiente añade (a) **ρ** que corrige la subestimación de empates/marcadores bajos (clave en knockouts cerrados), y (b) **time-decay ξ** (partidos viejos pesan menos). Karlis-Ntzoufras bivariado es más elegante pero la ganancia es marginal y es más frágil → **no lo usamos**.

**El truco ganador:** estimar las fuerzas de ataque/defensa α/β **sobre xG en vez de goles** ("expected Dixon-Coles"). Ruta pragmática: Poisson sobre xG continuo (la verosimilitud Poisson admite no-enteros). Con pocos partidos por selección, xG reduce drásticamente el ruido de finalización — ahí ganamos.

**Elo como prior:** mapear `dr` (diff de Elo + localía; casi todo neutral salvo MEX en altitud) → diferencia de goles esperada, calibrada con WC2018+2022. Es el patrón de FiveThirtyEight SPI y del modelo open-source WC2026 (Hicruben: Elo+Dixon-Coles+Monte Carlo).

**Librería:** `penaltyblog` (Dixon-Coles listo) + `scipy.optimize` para la versión custom sobre xG.

## 3. Nuestro xG propio (la ventaja diferencial)

WhoScored **no da xG**; StatsBomb **sí** (`shot_statsbomb_xg`). Entrenamos en StatsBomb y aplicamos a WhoScored.

**Regla de oro de transferibilidad:** entrenar SOLO con features comunes a ambos proveedores. Los freeze-frames (defensores/portero en la trayectoria) suben mucho el modelo PERO WhoScored no los tiene → **excluirlos** (si no, queda indefinido al puntuar).

**Feature set reducido (entrenable en SB, puntuable en WS):**
- **Distancia** a portería (m) — predictor #1
- **Ángulo** subtendido por los palos (rad) — #2
- **Parte del cuerpo** {pie, cabeza, otro}
- **Tipo de jugada** {open play, set piece, corner, free kick}
- (opcional) tipo de asistencia {pase, centro, through ball}
- **Penales = constante 0.79** (no modelar geométricamente)

**Crítico — normalizar coordenadas a METROS** antes de distancia/ángulo (SB es 120×80, WhoScored 0-100×0-100). Usar `kloppy`/`mplsoccer.Standardizer` o conversión manual (cancha 105×68, arco 7.32m).

**Algoritmo:** regresión logística (lo que usa Opta, bien calibrada) como baseline; LightGBM calibrado como avanzado. **La calibración importa más que el AUC** (al sumar xG a nivel equipo, el sesgo se acumula): `CalibratedClassifierCV` (Platt/isotonic), reliability diagram, Brier objetivo ≈0.08.

**Validación de transferencia (no saltar):** entrenar en WC2018, validar en WC2022; luego sumar xG-WhoScored por equipo del WC2026 y comparar con goles reales (debe aproximar). Sanity: penal≈0.79, cabezazo < pie a igual distancia.

**Complemento barato:** **xT (Expected Threat, Karun Singh)** — sin ML, corre directo sobre coords WhoScored, baja varianza por partido (integra cientos de acciones, no solo tiros). **VAEP NO** (overkill para predecir resultados; reservar para valorar jugadores). Librería: `socceraction` (xT + SPADL + loaders SB y WhoScored).

## 4. Devigging + blending con el mercado

**Devigging (quitar margen):** NO usar el método proporcional (subestima al favorito por el favorite-longshot bias). Usar **Power method** (default) o **Shin** (cross-check) — ambos corrigen el sesgo. En outrights de muchos equipos el overround es 15-40% y el sesgo es máximo → crítico. Mercados de predicción (Kalshi/Polymarket) ya son casi limpios → usar mid-price directo. Librería: `shin` (pip) o implementación Power con `scipy.brentq`.

**Benchmark = Pinnacle / Betfair** (los más sharp; Pinnacle closing r²≈0.997 con resultados reales), no el promedio de las 25 casas.

**Blend:** **logarithmic opinion pool** (media geométrica de odds, renormalizada) — gana empíricamente a la media aritmética (Satopää; Metaculus Brier 0.130 vs 0.138):
```
p_i ∝ p_modelo_i^(1-w) · p_mercado_i^(w)   (renormalizar)
```
con **w ≈ 0.75-0.85** al mercado (calibrar w minimizando log-loss out-of-sample). El mercado es el prior regularizador; el modelo aporta la corrección marginal (sobre todo el tilt de longshot-bias y los equipos sobre/infra-rindiendo xG).

## 5. Simulación del torneo (Monte Carlo)

- **100,000 simulaciones** (estándar de industria; SE≈±0.3pp). 10K solo para ranking rápido.
- Bracket fijo R32→Final. Validar el motor contra una **convolución analítica/DP** (oráculo exacto con matriz `p` determinista) para cazar bugs de cableado.
- **Resolución de knockout** (no hay empate): regulación (muestrear marcador del Dixon-Coles) → si empate, **prórroga a ⅓ de fuerza** (favorito ~68% cuando se decide antes de penales) → si sigue, **penales encogidos a ~55-57%** al favorito (NO 50/50 puro, NO fuerza completa; evidencia 538 + Csató 2026).
- En R32: **congelar resultados ya jugados**, simular solo lo que falta (condicionamiento intra-torneo).

## 6. Evaluación y backtesting (sin leakage)

- **Métrica principal: RPS (Ranked Probability Score)** — respeta el orden H/D/A (acumulativo). Reportar **también Brier y log-loss** (hay debate Wheatcroft sobre RPS).
- **Skill score vs mercado:** `1 − RPS_modelo / RPS_mercado` (>0 = batimos al mercado). Es la métrica que importa.
- **Backtest walk-forward con barrera de información** = primer partido del torneo. Entrenar SOLO con partidos anteriores; testear en los 64 partidos de WC2018 y 128 de WC2022 (que tenemos en StatsBomb). Refit de ratings cronológico, features point-in-time, scaler solo en train. **Nunca k-fold aleatorio.**
- Benchmarks de referencia: bookies RPS≈0.20; ensembles fuertes ≈0.19; el SDR-Elo del paper WC2026 llegó a ≈0.127.

## 7. Guardas contra overfitting (CRÍTICO — datos escasos)

Pocos partidos por selección → riesgo alto. Reglas:
1. **~5-10 features efectivas**, no docenas. Elo-diff como resumen de fuerza (no estimar α/β separados e inestables por equipo si hay pocos partidos).
2. **Regularización**: L1/Lasso con regla **1-SE** (lambda más grande dentro de 1 SE del óptimo). GBM con `max_depth` bajo + early stopping.
3. **Entrenar el xG en universo amplio** (todo StatsBomb histórico), no solo Mundiales.
4. **Shrinkage al mercado** = el regularizador más fuerte (reduce varianza en las colas).
5. **Fallback Elo-only** para equipos con poca historia.

## 8. Estrategia de la POLLA (el objetivo real)

Maximizar **P(quedar 1º entre N)**, no aciertos esperados (Kaplan-Garstka 2001; Clair-Letscher 2007).

- **Leverage = P_modelo / ownership_público.** >1.5 = infravalorado (comprar); <1 = trampa (sobre-elegido).
- **Mejores picks = {P_modelo > P_mercado} ∩ {leverage alto}** → típicamente un **campeón sólido pero sub-elegido**.
- **Escalar el contrarianismo según el pool:** pool chico → casi chalk; pool grande con puntos crecientes → **campeón/finalistas diferenciados** (con N grande, ir all-chalk = no puedes ganar).
- **Ownership en polla colombiana:** ojo con la sobre-elección de **Colombia / Brasil / Argentina** (sesgo nacional + camisetas grandes) → ahí está el leverage negativo a evitar y el positivo a explotar en otros.
- **Decisión final por simulación:** generar brackets candidatos desde P_modelo, simular el campo con ownership, elegir el que **maximiza P(1º)**.

---

## 9. Plan de construcción (Fase 2, por etapas)

| # | Entregable | Datos/Librería | ROI |
|---|---|---|---|
| **0** | Baseline de mercado (devig Power + consenso 3 mercados) | `market_odds`, `odds_quotes` · `shin`/scipy | Benchmark obligatorio |
| **1** | Modelo xG propio (logística/LightGBM, calibrado) | StatsBomb→WhoScored · sklearn, socceraction | **Ventaja diferencial** |
| **2** | Fuerzas xGF/xGA + xT por equipo | `events` + match_map | Inputs de fuerza |
| **3** | Motor de partido Elo→Dixon-Coles(xG) → 1X2 | `elo_ratings` + xG · penaltyblog/scipy | Núcleo |
| **4** | Blend log-pool con mercado (w calibrado) | capas 0+3 | Calibración |
| **5** | Monte Carlo 100K del bracket (ET+penales) | numpy | P(campeón/avance) |
| **6** | Backtest WC2018/2022 (RPS, skill vs mercado) | StatsBomb | Validación |
| **7** | Capa de polla (leverage, ownership, P(1º)) | salidas 4-5 | **Decisión final** |

**Orden recomendado:** 0 → 1 → 3 → 4 → 5 (MVP predictivo) → 6 (validar) → 2 y 7 (refinar y decidir picks).

## 10. Resumen ejecutivo (qué construimos)

> **Un híbrido Elo→Dixon-Coles-sobre-xG, blendeado con el consenso de mercado (devigueado), simulado 100K veces por el bracket, validado con RPS contra WC2018/22, y traducido a picks de polla por leverage/ownership.** El mercado es el ancla; nuestro xG propio (entrenado en StatsBomb, aplicado a WhoScored) es el edge; la estrategia contrarian de polla es cómo se convierte en ganar.

## Fuentes (selección)

- Dixon & Coles 1997 (JRSS-C); Karlis-Ntzoufras 2003; Maher 1982.
- Leitner-Zeileis-Hornik 2010 (Bookmaker Consensus); Groll et al. 2019 (hybrid RF).
- Predicting WC2026 con SDR de Elo (arXiv 2606.24171); On Elo WC2018 (arXiv 1806.01930).
- xG: StatsBomb "Upgrading xG"; Soccermatics (Sumpter); KU Leuven freeze-frames.
- xT (Karun Singh); VAEP/socceraction (Decroos KDD 2019).
- Devig: Štrumbelj 2014; Shin 1993; Buchdahl "Wisdom of the Crowd".
- Blend: Satopää 2014 (geo-mean of odds); Genest (log pool); 538 SPI post-mortem (transferscience).
- Monte Carlo / penales: 538 "Extra Time isn't a Crapshoot"; Csató-Petróczy 2026.
- Métricas: Constantinou-Fenton 2012 (RPS); Wheatcroft 2019; Gneiting 2007 (calibration+sharpness).
- Polla: Kaplan-Garstka 2001 (Management Science); Clair-Letscher 2007 (Operations Research).
- Modelo open-source WC2026: github.com/Hicruben/world-cup-2026-prediction-model
